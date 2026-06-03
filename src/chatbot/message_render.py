from __future__ import annotations

import html
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from src.chatbot.settings import get_settings


def safe_text(text: Any) -> str:
    return html.escape(str(text), quote=False).replace("\r", "").strip()


def truncate_text(text: str, max_len: int | None = None) -> str:
    limit = max_len or get_settings().max_reply_text_length
    clean = str(text).strip()
    if len(clean) <= limit:
        return clean
    window = clean[: max(0, limit - 8)].rstrip()
    min_pos = min(20, max(1, int(limit * 0.45)))
    best = -1
    for mark in ("。", "？", "！", "\n", "…", ".", "?", "!"):
        pos = window.rfind(mark)
        if pos >= min_pos:
            best = max(best, pos + len(mark))
    if best > 0:
        return _trim_dangling_kaomoji(window[:best].strip())
    for mark in ("，", "、", "；", ";", " "):
        pos = window.rfind(mark)
        if pos >= min_pos:
            return _trim_dangling_kaomoji(window[:pos].rstrip("，、；;：:") + "…")
    return _trim_dangling_kaomoji(window.rstrip("，、；;：:") + "…")


def _trim_dangling_kaomoji(text: str) -> str:
    last_open = max(text.rfind("("), text.rfind("（"))
    last_close = max(text.rfind(")"), text.rfind("）"))
    if last_open > last_close and len(text) - last_open <= 14:
        return text[:last_open].rstrip()
    return text


def paginate_list(items: Sequence[Any], page: int = 1, page_size: int = 10) -> tuple[list[Any], int]:
    page_size = max(1, page_size)
    total_pages = max(1, (len(items) + page_size - 1) // page_size)
    current = min(max(1, page), total_pages)
    start = (current - 1) * page_size
    return list(items[start : start + page_size]), total_pages


def render_kv(title: str, data: Mapping[str, Any]) -> str:
    lines = [safe_text(title)]
    lines.extend(f"{safe_text(key)}：{safe_text(value)}" for key, value in data.items())
    return truncate_text("\n".join(lines))


def render_command_help(commands: Mapping[str, Iterable[str]], title: str = "Bot 命令菜单") -> str:
    lines = [title, "帮助入口：/bot。"]
    for group, items in commands.items():
        lines.append("")
        lines.append(f"[{group}]")
        lines.extend(str(item) for item in items)
    return truncate_text("\n".join(lines))


def render_rank(title: str, rows: Sequence[tuple[str, Any]], *, page: int = 1) -> str:
    page_rows, total_pages = paginate_list(rows, page, 10)
    lines = [f"{title}（第 {page}/{total_pages} 页）"]
    for index, (name, value) in enumerate(page_rows, start=(page - 1) * 10 + 1):
        lines.append(f"{index}. {name}：{value}")
    return truncate_text("\n".join(lines))
