from __future__ import annotations

from nonebot.adapters import Event
from nonebot.compat import model_dump

from src.chatbot.settings import get_settings


def normalize_user_id(user_id: int | str | None) -> str:
    return "" if user_id is None else str(user_id)


def is_owner(user_id: int | str | None) -> bool:
    user = normalize_user_id(user_id)
    return bool(user and user in {str(item) for item in get_settings().owner_ids})


def is_admin(user_id: int | str | None) -> bool:
    user = normalize_user_id(user_id)
    admins = {str(item) for item in get_settings().admin_ids}
    return is_owner(user) or bool(user and user in admins)


def get_user_id(event: Event) -> str:
    try:
        return event.get_user_id()
    except Exception:
        raw = model_dump(event)
        return normalize_user_id(raw.get("user_id"))


def get_group_id(event: Event) -> str | None:
    raw = model_dump(event)
    group_id = raw.get("group_id")
    return str(group_id) if group_id is not None else None


def is_group_event(event: Event) -> bool:
    raw = model_dump(event)
    return raw.get("message_type") == "group" or raw.get("group_id") is not None


def is_private_event(event: Event) -> bool:
    raw = model_dump(event)
    return raw.get("message_type") == "private" and raw.get("group_id") is None


def require_admin(event: Event) -> bool:
    return is_admin(get_user_id(event))
