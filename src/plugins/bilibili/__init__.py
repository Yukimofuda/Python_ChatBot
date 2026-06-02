from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from nonebot import on_command, on_message
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot.adapters.onebot.v11.exception import ActionFailed
from nonebot.compat import model_dump
from nonebot.params import CommandArg

from src.chatbot.cooldown import CooldownManager
from src.chatbot.memory import scope_id
from src.chatbot.permissions import require_admin
from src.chatbot.security import cleanup_temp_files, format_file_size, sanitize_filename
from src.chatbot.settings import get_settings
from src.chatbot.storage import JsonPluginStorage
from src.chatbot.text import plain_text


settings = get_settings()
matcher = on_message(priority=20, block=False)
bili = on_command("bili", aliases={"b站"}, priority=5, block=True)
store = JsonPluginStorage("bilibili", default={"groups": {}, "recent_urls": {}})
cooldown = CooldownManager()

BILIBILI_URL_RE = re.compile(
    r"https?://(?:www\.bilibili\.com/video/[A-Za-z0-9]+/?[^\s，。！？)]*|"
    r"b23\.tv/[A-Za-z0-9]+|"
    r"bili2233\.cn/[A-Za-z0-9]+)"
)


@dataclass(frozen=True)
class BilibiliVideo:
    title: str
    path: Path
    webpage_url: str
    filesize: int | None


@matcher.handle()
async def handle_bilibili(bot: Bot, event: Event) -> None:
    if not settings.bilibili_enabled or bot.type != "OneBot V11":
        return

    text = plain_text(event)
    url = find_bilibili_url(text)
    if not url:
        return
    group = scope_id(event)
    if not group_enabled(group):
        return
    if is_recent_url(group, url):
        return
    remain = cooldown.check(
        "bilibili",
        group_id=group,
        seconds=settings.bilibili_cooldown_seconds,
        scope="group",
    )
    if remain > 0:
        return

    await matcher.send("检测到 B 站视频，正在解析 mp4...")
    try:
        video = await asyncio.to_thread(download_bilibili_video, url)
    except ImportError:
        await matcher.finish("B 站解析需要安装 yt-dlp：env -u PYTHONPATH python -m pip install yt-dlp")
    except Exception as exc:
        await matcher.finish(f"B 站视频解析失败：{exc}")

    remember_url(group, url)
    size_text = format_file_size(video.filesize)
    await matcher.send(f"{video.title}\n{size_text}\n{video.webpage_url}")
    try:
        await matcher.send(MessageSegment.video(video.path, timeout=120))
    except ActionFailed as exc:
        try:
            await send_video_as_file(bot, event, video)
        except Exception:
            cleanup_video(video.path)
            await matcher.finish(
                "视频已解析，但平台发送失败。"
                f"\n原因：{exc.message or exc.wording}"
                "\n本地临时 mp4 已删除。"
            )
        cleanup_video(video.path)
        await matcher.finish("视频消息发送失败，已改为文件发送。本地临时 mp4 已删除。")

    cleanup_video(video.path)
    await matcher.finish()


@bili.handle()
async def handle_bili_command(event: Event, args=CommandArg()) -> None:
    text = args.extract_plain_text().strip()
    group = scope_id(event)
    if text == "status" or not text:
        await bili.finish(
            "\n".join(
                [
                    f"B站解析：{'开启' if group_enabled(group) else '关闭'}",
                    f"最大视频：{settings.bilibili_max_video_mb} MB",
                    f"群冷却：{settings.bilibili_cooldown_seconds} 秒",
                    f"下载目录：{Path(settings.bilibili_download_dir).expanduser()}",
                ]
            )
        )
    if text in {"on", "off"}:
        if not require_admin(event):
            await bili.finish("B站解析开关需要管理员权限。")
        set_group_enabled(group, text == "on")
        await bili.finish(f"B站解析已{'开启' if text == 'on' else '关闭'}。")
    if text == "clean":
        if not require_admin(event):
            await bili.finish("清理 B站临时文件需要管理员权限。")
        count = cleanup_temp_files(Path(settings.bilibili_download_dir).expanduser(), 0)
        await bili.finish(f"已清理 {count} 个 B站临时文件。")
    await bili.finish("用法：/bili status、/bili on、/bili off、/bili clean")


def find_bilibili_url(text: str) -> str | None:
    match = BILIBILI_URL_RE.search(text)
    if not match:
        return None
    url = match.group(0)
    parsed = urlparse(url)
    return url if parsed.scheme and parsed.netloc else None


def group_enabled(group: str) -> bool:
    return bool(store.read().get("groups", {}).get(group, {}).get("enabled", True))


def set_group_enabled(group: str, enabled: bool) -> None:
    def mutate(data: dict) -> None:
        data.setdefault("groups", {}).setdefault(group, {})["enabled"] = enabled

    store.update(mutate)


def is_recent_url(group: str, url: str) -> bool:
    key = f"{group}:{url}"
    timestamp = float(store.read().get("recent_urls", {}).get(key, 0))
    return time.time() - timestamp < 300


def remember_url(group: str, url: str) -> None:
    key = f"{group}:{url}"

    def mutate(data: dict) -> None:
        recent = data.setdefault("recent_urls", {})
        recent[key] = time.time()
        now = time.time()
        for item_key in [item for item, timestamp in recent.items() if now - float(timestamp) > 3600]:
            recent.pop(item_key, None)

    store.update(mutate)


def download_bilibili_video(url: str) -> BilibiliVideo:
    from yt_dlp import YoutubeDL

    output_dir = Path(settings.bilibili_download_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(output_dir / f"{uuid.uuid4().hex}.%(ext)s")
    max_filesize = settings.bilibili_max_video_mb * 1024 * 1024

    options = {
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best[ext=mp4]/best",
        "outtmpl": output_template,
        "merge_output_format": "mp4",
        "max_filesize": max_filesize,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)

    path = Path(filename)
    if path.suffix != ".mp4":
        merged = path.with_suffix(".mp4")
        if merged.exists():
            path = merged

    if not path.exists():
        matches = sorted(output_dir.glob(f"{Path(filename).stem}*"), key=lambda p: p.stat().st_mtime)
        if not matches:
            raise ValueError("没有生成 mp4 文件")
        path = matches[-1]

    filesize = path.stat().st_size
    if filesize > max_filesize:
        path.unlink(missing_ok=True)
        raise ValueError(f"视频超过 {settings.bilibili_max_video_mb} MB，已跳过")

    return BilibiliVideo(
        title=str(info.get("title") or "Bilibili video"),
        path=path,
        webpage_url=str(info.get("webpage_url") or url),
        filesize=filesize,
    )


async def send_video_as_file(bot: Bot, event: Event, video: BilibiliVideo) -> None:
    raw = model_dump(event)
    safe_name = sanitize_filename(video.title) + ".mp4"
    if raw.get("message_type") == "group" and raw.get("group_id") is not None:
        await bot.call_api(
            "upload_group_file",
            group_id=int(raw["group_id"]),
            file=str(video.path),
            name=safe_name,
        )
        return
    if raw.get("user_id") is not None:
        await bot.call_api(
            "upload_private_file",
            user_id=int(raw["user_id"]),
            file=str(video.path),
            name=safe_name,
        )
        return
    raise ValueError("无法判断发送文件的目标会话")

def cleanup_video(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
