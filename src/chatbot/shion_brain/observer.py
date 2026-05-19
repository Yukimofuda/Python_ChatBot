from __future__ import annotations

import re
import uuid

from nonebot.adapters import Bot, Event
from nonebot.compat import model_dump

from src.chatbot.shion_brain.models import Observation, utc_now


COMMAND_PREFIXES = ("/", "!")
SENSITIVE_RE = re.compile(r"(token|api[_-]?key|密码|passwd|password|secret|cookie)", re.I)
NAME_ALIASES = (
    "shion",
    "小栞",
    "栞音",
    "しおん",
    "栞音酱",
    "七瀬栞音",
    "七濑栞音",
    "nanase shion",
)


def event_to_observation(bot: Bot, event: Event) -> Observation:
    raw = model_dump(event)
    text = _plain_text(event)
    group_id = str(raw.get("group_id") or f"private:{raw.get('user_id', 'unknown')}")
    user_id = _safe_call("", event.get_user_id)
    message_id = str(raw.get("message_id") or uuid.uuid4().hex)
    message_type = str(raw.get("message_type") or raw.get("post_type") or "")
    mentioned_by_at = _mentions_bot(raw, bot.self_id)
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
    }
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
    )


def _plain_text(event: Event) -> str:
    try:
        return event.get_plaintext().strip()
    except Exception:
        try:
            return str(event.get_message()).strip()
        except Exception:
            return ""


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
