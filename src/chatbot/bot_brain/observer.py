from __future__ import annotations

import re
import uuid
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from nonebot.adapters import Bot, Event

from src.chatbot.bot_brain.models import Observation, utc_now
from src.chatbot.bot_brain.social_cognition.conversation_context import extract_reply_metadata


COMMAND_PREFIXES = ("/", "!")
SENSITIVE_RE = re.compile(r"(token|api[_-]?key|密码|passwd|password|secret|cookie)", re.I)
NAME_ALIASES = (
    "bot",
    "Bot",
    "Bot",
    "しおん",
    "Bot酱",
    "Bot",
    "Bot",
    "generic bot",
)


def event_to_observation(bot: "Bot", event: "Event") -> Observation:
    try:
        from nonebot.compat import model_dump
    except Exception as exc:  # pragma: no cover - only hit in stripped unit environments
        raise RuntimeError("NoneBot runtime is required for event_to_observation") from exc

    raw = model_dump(event)
    text = _plain_text(event)
    raw_message_text = _raw_message_text(event)
    group_id = str(raw.get("group_id") or f"private:{raw.get('user_id', 'unknown')}")
    user_id = _safe_call("", event.get_user_id)
    sender_display_name = _sender_display_name(raw)
    message_id = str(raw.get("message_id") or uuid.uuid4().hex)
    message_type = str(raw.get("message_type") or raw.get("post_type") or "")
    mentioned_by_at = _mentions_bot(raw, bot.self_id)
    mentioned_user_ids, mentioned_user_display_names = _mentioned_users(raw, bot.self_id)
    primary_target_user_id = mentioned_user_ids[0] if mentioned_user_ids else None
    mentioned_by_name = _mentions_name(text)
    mentions_bot = mentioned_by_at or mentioned_by_name
    features = {
        "length": len(text),
        "mentioned_by_at": mentioned_by_at,
        "mentioned_by_name": mentioned_by_name,
        "has_question": "?" in text or "？" in text,
        "has_laugh": any(word in text for word in ("哈哈", "笑死", "绷不住")),
        "has_distress": any(word in text for word in ("救命", "完了", "寄了", "崩溃", "写不完")),
        "has_sensitive": bool(SENSITIVE_RE.search(text)),
        "sender_id": user_id,
        "sender_display_name": sender_display_name,
        "mentioned_user_ids": mentioned_user_ids,
        "mentioned_display_names": mentioned_user_display_names,
        "raw_message_text": raw_message_text,
        "bot_id": str(bot.self_id),
        "self_id": str(bot.self_id),
    }
    features.update(extract_reply_metadata(raw, text=text, raw_message_text=raw_message_text))
    return Observation(
        id=uuid.uuid4().hex,
        group_id=group_id,
        user_id=user_id,
        message_id=message_id,
        text=text[:1000],
        timestamp=utc_now(),
        message_type=message_type,
        is_command=text.startswith(COMMAND_PREFIXES),
        mentions_bot=mentions_bot,
        features=features,
        sender_id=user_id,
        sender_display_name=sender_display_name,
        raw_message_text=raw_message_text,
        mentioned_user_ids=mentioned_user_ids,
        primary_target_user_id=primary_target_user_id,
        mentioned_user_display_names=mentioned_user_display_names,
    )


def _plain_text(event: Any) -> str:
    try:
        return event.get_plaintext().strip()
    except Exception:
        try:
            return str(event.get_message()).strip()
        except Exception:
            return ""


def _raw_message_text(event: Any) -> str:
    try:
        return str(event.get_message()).strip()
    except Exception:
        return _plain_text(event)


def _sender_display_name(raw: dict) -> str:
    sender = raw.get("sender") or {}
    if not isinstance(sender, dict):
        return ""
    return str(sender.get("card") or sender.get("nickname") or sender.get("name") or "").strip()


def _mentioned_users(raw: dict, self_id: str) -> tuple[list[str], dict[str, str]]:
    ids: list[str] = []
    names: dict[str, str] = {}
    for segment in raw.get("message", []):
        if not isinstance(segment, dict) or segment.get("type") != "at":
            continue
        data = segment.get("data") or {}
        qq = str(data.get("qq") or "").strip()
        if not qq or qq == "all" or qq == str(self_id):
            continue
        if qq not in ids:
            ids.append(qq)
        display = str(data.get("name") or data.get("nickname") or data.get("card") or "").strip()
        if display:
            names[qq] = display
    return ids, names


def _mentions_bot(raw: dict, self_id: str) -> bool:
    for segment in raw.get("message", []):
        if isinstance(segment, dict) and segment.get("type") == "at":
            if str(segment.get("data", {}).get("qq")) == str(self_id):
                return True
    return False


def _mentions_name(text: str) -> bool:
    lowered = text.lower()
    return any(name.lower() in lowered for name in NAME_ALIASES)


def _safe_call(default: str, fn) -> str:
    try:
        return str(fn())
    except Exception:
        return default
