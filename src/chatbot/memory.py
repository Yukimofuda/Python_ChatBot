from __future__ import annotations

from nonebot.adapters import Event

from src.chatbot.permissions import get_group_id, get_user_id


def scope_id(event: Event) -> str:
    """Return a generic storage scope for group or private conversations."""
    return get_group_id(event) or f"private:{get_user_id(event)}"
