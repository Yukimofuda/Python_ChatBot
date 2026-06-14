from __future__ import annotations

from nonebot.adapters import Event


def user_id(event: Event) -> str:
    try:
        return event.get_user_id()
    except Exception:
        return "unknown"


def plain_text(event: Event) -> str:
    try:
        return event.get_plaintext().strip()
    except Exception:
        return str(event.get_message()).strip()
