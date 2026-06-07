from __future__ import annotations

import hashlib

from nonebot.adapters import Event
from nonebot.compat import model_dump

from src.chatbot.settings import get_settings


def _stable_key(prefix: str, raw_value: int | str | None) -> str:
    raw = "" if raw_value is None else str(raw_value).strip()
    if not raw:
        return f"{prefix}-unknown"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{digest}"


def actor_key_from_value(raw_value: int | str | None) -> str:
    return _stable_key("actor", raw_value)


def room_key_from_value(raw_value: int | str | None) -> str:
    return _stable_key("room", raw_value)


def event_actor_key(event: Event) -> str:
    try:
        return actor_key_from_value(event.get_user_id())
    except Exception:
        raw = model_dump(event)
        return actor_key_from_value(raw.get("user_id"))


def event_room_key(event: Event) -> str | None:
    raw = model_dump(event)
    room_id = raw.get("group_id")
    if room_id is not None:
        return room_key_from_value(room_id)
    return None


def is_group_event(event: Event) -> bool:
    raw = model_dump(event)
    return raw.get("message_type") == "group" or raw.get("group_id") is not None


def is_private_event(event: Event) -> bool:
    raw = model_dump(event)
    return raw.get("message_type") == "private" and raw.get("group_id") is None


def is_admin(actor_id: int | str | None) -> bool:
    if actor_id is None:
        return False
    allowed = {actor_key_from_value(value) for value in get_settings().admin_ids}
    return actor_key_from_value(actor_id) in allowed


def require_admin(event: Event) -> bool:
    try:
        actor_id = event.get_user_id()
    except Exception:
        actor_id = model_dump(event).get("user_id")
    return is_admin(actor_id)
