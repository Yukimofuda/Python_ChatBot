from __future__ import annotations

import asyncio
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from nonebot import on_command, on_message
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot.compat import model_dump
from nonebot.params import CommandArg

from src.chatbot.bilibili_url_extract import (
    BilibiliCardInfo,
    build_preview_text,
    extract_bilibili_card_info,
)
from src.chatbot.cooldown import CooldownManager
from src.chatbot.memory import scope_id
from src.chatbot.permissions import event_room_key, require_admin
from src.chatbot.security import cleanup_temp_files, format_file_size, sanitize_filename
from src.chatbot.settings import get_settings
from src.chatbot.storage import JsonPluginStorage


settings = get_settings()
matcher = on_message(priority=20, block=False)
bili = on_command("bili", aliases={"b站"}, priority=5, block=True)
store = JsonPluginStorage("bilibili", default={"rooms": {}, "recent_urls": {}})
cooldown = CooldownManager()


@dataclass(frozen=True)
class BilibiliVideo:
    title: str
    filename: str
    path: Path
    webpage_url: str
    filesize: int | None


@matcher.handle()
async def handle_bilibili(bot: Bot, event: Event) -> None:
    if not settings.bilibili_enabled or bot.type != "OneBot V11":
        return

    info = await extract_bilibili_card_info(bot, event)
    if not info.raw_url and not info.video_url:
        return

    scope = scope_id(event)
    room_key = event_room_key(event)
    if not room_enabled(scope):
        return

    dedupe_key = info.video_url or info.raw_url or ""
    if dedupe_key and is_recent_url(scope, dedupe_key):
        return
    remain = cooldown.check(
        "bilibili",
        room_key=room_key or scope,
        seconds=settings.bilibili_cooldown_seconds,
        scope="room",
    )
    if remain > 0:
        return

    if not info.video_url:
        if info.is_dynamic:
            return
        return

    await send_preview(info)
    if dedupe_key:
        remember_url(scope, dedupe_key)

    try:
        video = await asyncio.to_thread(download_bilibili_video, info.video_url)
    except Exception as exc:
        await matcher.finish(classify_bilibili_download_error(exc))

    try:
        await upload_video_file(bot, event, video)
    finally:
        cleanup_video(video)

    await matcher.finish()


@bili.handle()
async def handle_bili_command(event: Event, args=CommandArg()) -> None:
    text = args.extract_plain_text().strip()
    scope = scope_id(event)
    if text == "status" or not text:
        await bili.finish(
            "\n".join(
                [
                    f"B站解析：{'开启' if room_enabled(scope) else '关闭'}",
                    f"最大视频：{settings.bilibili_max_video_mb} MB",
                    f"群冷却：{settings.bilibili_cooldown_seconds} 秒",
                    f"下载目录：{Path(settings.bilibili_download_dir).expanduser()}",
                    "发送方式：封面预览 + 文件上传",
                ]
            )
        )
    if text in {"on", "off"}:
        if not require_admin(event):
            await bili.finish("B站解析开关需要管理员权限。")
        set_room_enabled(scope, text == "on")
        await bili.finish(f"B站解析已{'开启' if text == 'on' else '关闭'}。")
    if text == "clean":
        if not require_admin(event):
            await bili.finish("清理 B站临时文件需要管理员权限。")
        count = cleanup_temp_files(Path(settings.bilibili_download_dir).expanduser(), 0)
        await bili.finish(f"已清理 {count} 个 B站临时文件。")
    await bili.finish("用法：/bili status、/bili on、/bili off、/bili clean")


async def send_preview(info: BilibiliCardInfo) -> None:
    await matcher.send(build_preview_text(info))
    if info.cover:
        try:
            await matcher.send(MessageSegment.image(info.cover))
        except Exception:
            pass


def room_enabled(scope: str) -> bool:
    return bool(store.read().get("rooms", {}).get(scope, {}).get("enabled", True))


def set_room_enabled(scope: str, enabled: bool) -> None:
    def mutate(data: dict) -> None:
        data.setdefault("rooms", {}).setdefault(scope, {})["enabled"] = enabled

    store.update(mutate)


def is_recent_url(scope: str, url: str) -> bool:
    key = f"{scope}:{url}"
    timestamp = float(store.read().get("recent_urls", {}).get(key, 0))
    return time.time() - timestamp < 300


def remember_url(scope: str, url: str) -> None:
    key = f"{scope}:{url}"

    def mutate(data: dict) -> None:
        recent = data.setdefault("recent_urls", {})
        recent[key] = time.time()
        now = time.time()
        for item_key in [item for item, stamp in recent.items() if now - float(stamp) > 3600]:
            recent.pop(item_key, None)

    store.update(mutate)


def download_bilibili_video(url: str) -> BilibiliVideo:
    from yt_dlp import YoutubeDL

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("缺少 ffmpeg")

    output_dir = Path(settings.bilibili_download_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(output_dir / "%(title).80s_%(id)s.%(ext)s")
    max_filesize = settings.bilibili_max_video_mb * 1024 * 1024
    ydl_opts = {
        "outtmpl": output_template,
        "format": "bv*[ext=mp4]+ba[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "final_ext": "mp4",
        "noplaylist": True,
        "quiet": True,
        "socket_timeout": 20,
        "retries": 3,
        "fragment_retries": 3,
    }
    cookie_file = settings.bilibili_cookie_file.strip()
    if cookie_file:
        ydl_opts["cookiefile"] = cookie_file

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)

    source_path = Path(filename)
    final_path = _ensure_mp4(source_path, output_dir)
    if not final_path.exists() or final_path.stat().st_size <= 0:
        raise ValueError("没有生成有效 mp4 文件")
    filesize = final_path.stat().st_size
    if filesize > max_filesize:
        final_path.unlink(missing_ok=True)
        raise ValueError(f"视频超过 {settings.bilibili_max_video_mb} MB，已跳过")

    return BilibiliVideo(
        title=str(info.get("title") or "Bilibili video"),
        filename=sanitize_filename(final_path.name),
        path=final_path,
        webpage_url=str(info.get("webpage_url") or url),
        filesize=filesize,
    )


async def upload_video_file(bot: Bot, event: Event, video: BilibiliVideo) -> None:
    raw = model_dump(event)
    if raw.get("message_type") == "group" and raw.get("group_id") is not None:
        await bot.call_api(
            "upload_group_file",
            group_id=int(raw["group_id"]),
            file=str(video.path),
            name=video.filename,
        )
        await matcher.send(f"{video.title}\n{format_file_size(video.filesize)}\n{video.webpage_url}")
        return
    if raw.get("user_id") is not None:
        await bot.call_api(
            "upload_private_file",
            user_id=int(raw["user_id"]),
            file=str(video.path),
            name=video.filename,
        )
        await matcher.send(f"{video.title}\n{format_file_size(video.filesize)}\n{video.webpage_url}")
        return
    raise ValueError("无法判断发送文件的目标会话")


def classify_bilibili_download_error(exc: Exception) -> str:
    message = str(exc or "")
    if "ffmpeg" in message.lower():
        return "解析 B 站视频前需要先安装 ffmpeg。"
    if "超过" in message:
        return message
    return "B站视频解析失败，请稍后再试。"


def cleanup_video(video: BilibiliVideo | Path) -> None:
    path = video.path if isinstance(video, BilibiliVideo) else video
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _ensure_mp4(path: Path, output_dir: Path) -> Path:
    if path.suffix.lower() == ".mp4" and path.exists():
        return path
    merged = path.with_suffix(".mp4")
    if merged.exists():
        return merged
    matches = sorted(output_dir.glob(f"{path.stem}*"), key=lambda item: item.stat().st_mtime)
    for candidate in reversed(matches):
        if candidate.suffix.lower() == ".mp4":
            return candidate
    return path
