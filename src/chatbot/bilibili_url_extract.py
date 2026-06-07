from __future__ import annotations

import asyncio
import html
import json
import re
from dataclasses import dataclass
from typing import Any, Iterator, TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

if TYPE_CHECKING:
    from nonebot.adapters import Bot, Event


TRAILING_GARBAGE = "，。！？、；：,.!?;:)]）】}\"'》> \n\r\t"
VIDEO_URL_RE = re.compile(r"https?://(?:www\.|m\.)?bilibili\.com/video/(BV[0-9A-Za-z]{10,}|av\d{1,20})[^\s<>'\"，。！？]*", re.I)
SHORT_URL_RE = re.compile(r"https?://(?:www\.)?(b23\.tv|bili2233\.cn)/[A-Za-z0-9]+[^\s<>'\"，。！？]*", re.I)
DYNAMIC_URL_RE = re.compile(r"https?://(?:t\.bilibili\.com/\d+|(?:www\.)?bilibili\.com/opus/\d+)[^\s<>'\"，。！？]*", re.I)
PERCENT_ENCODED_URL_RE = re.compile(r"https%3A%2F%2F[^\s\"'<>]+", re.I)
BVID_RE = re.compile(r"\b(BV[0-9A-Za-z]{10,})\b")
AV_RE = re.compile(r"\b(av\d{1,20})\b", re.I)
DYNAMIC_ID_RE = re.compile(r"(?:t\.bilibili\.com|bilibili\.com/opus)/(\d{1,20})", re.I)

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.bilibili.com/",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


@dataclass(frozen=True)
class BilibiliCardInfo:
    title: str | None = None
    desc: str | None = None
    cover: str | None = None
    raw_url: str | None = None
    video_url: str | None = None
    source: str = "unknown"
    is_dynamic: bool = False


@dataclass(frozen=True)
class BilibiliResolvedUrl:
    url: str | None
    kind: str
    source: str
    reason: str = ""


def build_preview_text(info: BilibiliCardInfo) -> str:
    parts = []
    if info.title:
        parts.append(info.title)
    if info.desc:
        parts.append(info.desc[:120])
    if info.video_url or info.raw_url:
        parts.append(info.video_url or info.raw_url or "")
    return "\n".join(part for part in parts if part) or "检测到 B 站链接。"


async def extract_bilibili_card_info(bot: Bot | None, event: Event) -> BilibiliCardInfo:
    del bot
    payload = _model_dump(event)
    strings = collect_strings_from_payload(payload)
    title = _first_match(strings, lambda item: _extract_by_key(item, {"title"}))
    desc = _first_match(strings, lambda item: _extract_by_key(item, {"desc", "summary", "content"}))
    cover = _first_match(strings, _extract_cover_url)
    raw_url = extract_bilibili_url_from_text("\n".join(strings))
    video_url = None
    source = "text"
    is_dynamic = bool(raw_url and _is_dynamic_url(raw_url))
    if raw_url:
        resolved = await resolve_bilibili_video_url(raw_url)
        video_url = resolved.url
        source = resolved.source
        if resolved.kind == "dynamic_without_video":
            is_dynamic = True
    return BilibiliCardInfo(
        title=title,
        desc=desc,
        cover=cover,
        raw_url=raw_url,
        video_url=video_url,
        source=source,
        is_dynamic=is_dynamic,
    )


def extract_bilibili_url_from_text(text: str) -> str | None:
    candidates = []
    for pattern in (VIDEO_URL_RE, SHORT_URL_RE, DYNAMIC_URL_RE, PERCENT_ENCODED_URL_RE):
        for match in pattern.finditer(text or ""):
            candidate = _trim_url(unquote(match.group(0)))
            normalized = normalize_bilibili_url(candidate)
            if normalized:
                candidates.append(normalized)
    direct = normalize_video_id_to_url(text or "")
    if direct:
        candidates.append(direct)
    return candidates[0] if candidates else None


def normalize_video_id_to_url(value: str) -> str | None:
    raw = _trim_url(unquote(value or ""))
    bvid = BVID_RE.search(raw)
    if bvid:
        return f"https://www.bilibili.com/video/{bvid.group(1)}"
    avid = AV_RE.search(raw)
    if avid:
        digits = re.sub(r"\D", "", avid.group(1))
        return f"https://www.bilibili.com/video/av{digits}"
    return None


def normalize_bilibili_url(candidate: str) -> str | None:
    direct = normalize_video_id_to_url(candidate)
    if direct:
        return direct
    text = _trim_url(candidate)
    if text.startswith("//"):
        text = "https:" + text
    elif text.startswith(("b23.tv/", "bili2233.cn/", "t.bilibili.com/", "www.bilibili.com/", "bilibili.com/")):
        text = "https://" + text
    parsed = urlparse(text)
    if not parsed.scheme or not parsed.netloc:
        return None
    host = parsed.netloc.lower()
    if host in {"b23.tv", "www.b23.tv", "bili2233.cn", "www.bili2233.cn"}:
        return strip_tracking_query(text)
    if host == "t.bilibili.com":
        return strip_tracking_query(text)
    if host in {"www.bilibili.com", "bilibili.com", "m.bilibili.com"}:
        if "/video/" in parsed.path:
            return strip_tracking_query(text)
        if parsed.path.startswith("/opus/"):
            return strip_tracking_query(text)
    return None


async def resolve_bilibili_video_url(raw_url: str) -> BilibiliResolvedUrl:
    normalized = normalize_bilibili_url(raw_url) or normalize_video_id_to_url(raw_url)
    if not normalized:
        return BilibiliResolvedUrl(None, "unknown", "input", "无法识别为 B 站链接")
    if "/video/" in normalized:
        return BilibiliResolvedUrl(normalized, "video", "normalized")
    if _is_short_url(normalized):
        return await asyncio.to_thread(_resolve_short_url, normalized)
    if _is_dynamic_url(normalized):
        return await asyncio.to_thread(_resolve_dynamic_url, normalized)
    return BilibiliResolvedUrl(None, "unknown", "normalized", "没有解析到可下载视频地址")


def strip_tracking_query(url: str) -> str:
    parsed = urlparse(str(url or ""))
    if not parsed.scheme or not parsed.netloc:
        return url
    keep = []
    for key, values in parse_qs(parsed.query, keep_blank_values=False).items():
        if key.lower() in {"p", "t"}:
            for value in values:
                keep.append(f"{key}={value}")
    query = ("?" + "&".join(keep)) if keep else ""
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}{query}"


def collect_strings_from_payload(obj: Any) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for value in iter_strings_deep(obj):
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            items.append(text)
    return items


def iter_strings_deep(obj: Any) -> Iterator[str]:
    if isinstance(obj, str):
        yield obj
        decoded = _decode_possible_json(obj)
        if decoded is not None and decoded != obj:
            yield from iter_strings_deep(decoded)
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(key, str):
                yield key
            yield from iter_strings_deep(value)
        return
    if isinstance(obj, (list, tuple, set)):
        for item in obj:
            yield from iter_strings_deep(item)


def _resolve_short_url(url: str) -> BilibiliResolvedUrl:
    class _NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, hdrs, newurl):
            return None

    opener = build_opener(_NoRedirect())
    request = Request(url, headers=REQUEST_HEADERS)
    try:
        opener.open(request, timeout=10)
    except HTTPError as exc:
        location = exc.headers.get("Location", "")
        direct = normalize_bilibili_url(location)
        if direct and "/video/" in direct:
            return BilibiliResolvedUrl(direct, "video", "short_url_redirect")
        if direct and _is_dynamic_url(direct):
            return _resolve_dynamic_url(direct)
    except URLError:
        return BilibiliResolvedUrl(None, "short_url_unresolved", "short_url", "网络错误")
    return BilibiliResolvedUrl(None, "short_url_unresolved", "short_url", "未获得跳转目标")


def _resolve_dynamic_url(url: str) -> BilibiliResolvedUrl:
    dynamic_id = _extract_dynamic_id(url)
    if not dynamic_id:
        return BilibiliResolvedUrl(None, "dynamic_without_video", "dynamic", "无法提取动态 ID")
    api = f"https://api.bilibili.com/x/polymer/web-dynamic/v1/detail?id={dynamic_id}"
    request = Request(api, headers=REQUEST_HEADERS)
    try:
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return BilibiliResolvedUrl(None, "dynamic_without_video", "dynamic", "动态解析失败")
    video = extract_bilibili_url_from_text(json.dumps(payload, ensure_ascii=False))
    if video and "/video/" in video:
        return BilibiliResolvedUrl(video, "video", "dynamic_api")
    return BilibiliResolvedUrl(None, "dynamic_without_video", "dynamic", "动态中没有视频")


def _extract_dynamic_id(url: str) -> str | None:
    match = DYNAMIC_ID_RE.search(url)
    return match.group(1) if match else None


def _extract_cover_url(text: str) -> str | None:
    for url in re.findall(r"https?://[^\s<>'\"]+", html.unescape(text or "")):
        if any(ext in url.lower() for ext in (".jpg", ".jpeg", ".png", ".webp")):
            return _trim_url(url)
    return None


def _extract_by_key(text: str, keys: set[str]) -> str | None:
    decoded = _decode_possible_json(text)
    if isinstance(decoded, dict):
        for key, value in decoded.items():
            if str(key).lower() in keys and isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _decode_possible_json(text: str) -> Any | None:
    candidate = html.unescape(str(text or "")).strip()
    if not candidate or candidate[0] not in "{[":
        return None
    try:
        return json.loads(candidate)
    except Exception:
        return None


def _first_match(values: list[str], extractor) -> str | None:
    for value in values:
        result = extractor(value)
        if result:
            return result
    return None


def _trim_url(value: str) -> str:
    return str(value or "").strip(TRAILING_GARBAGE)


def _is_short_url(url: str) -> bool:
    return "b23.tv/" in url or "bili2233.cn/" in url


def _is_dynamic_url(url: str) -> bool:
    return "t.bilibili.com/" in url or "/opus/" in url


def _model_dump(event: Any) -> Any:
    from nonebot.compat import model_dump

    return model_dump(event)
