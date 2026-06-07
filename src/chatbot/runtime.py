from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import nonebot
from nonebot.adapters import Bot, Event
from nonebot.compat import model_dump

from src.chatbot.permissions import event_actor_key, event_room_key
from src.chatbot.settings import get_settings


STARTED_AT = datetime.now(timezone.utc)
RECENT_MESSAGES: deque["MessageRecord"] = deque(maxlen=get_settings().recent_message_limit)


@dataclass(frozen=True)
class MessageRecord:
    time: str
    adapter: str
    event_type: str
    detail_type: str
    conversation: str
    speaker: str
    text: str


def _safe_call(default: str, fn) -> str:
    try:
        return str(fn())
    except Exception:
        return default


def record_message(bot: Bot, event: Event) -> None:
    raw = model_dump(event)
    detail_type = str(
        raw.get("message_type")
        or raw.get("notice_type")
        or raw.get("request_type")
        or raw.get("meta_event_type")
        or ""
    )
    text = _safe_call("", event.get_plaintext).strip()
    room_key = event_room_key(event)
    RECENT_MESSAGES.appendleft(
        MessageRecord(
            time=datetime.now(timezone.utc).isoformat(),
            adapter=bot.type,
            event_type=_safe_call("", event.get_type),
            detail_type=detail_type,
            conversation=room_key or "private",
            speaker=event_actor_key(event),
            text=text[:240],
        )
    )


def runtime_status() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    driver = nonebot.get_driver()
    bots = nonebot.get_bots()
    return {
        "ok": True,
        "bot_name": get_settings().bot_name,
        "started_at": STARTED_AT.isoformat(),
        "now": now.isoformat(),
        "uptime_seconds": int((now - STARTED_AT).total_seconds()),
        "driver": driver.type,
        "adapters": sorted(driver._adapters.keys()),
        "bots": [{"adapter": bot.type} for _, bot in sorted(bots.items())],
        "message_count": len(RECENT_MESSAGES),
        "onebot_ws_url": get_settings().onebot_ws_url,
        "admin": {"enabled": get_settings().admin_enabled, "token_required": bool(get_settings().admin_token)},
    }


def recent_messages() -> list[dict[str, Any]]:
    return [asdict(record) for record in RECENT_MESSAGES]
