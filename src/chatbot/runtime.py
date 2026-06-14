from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import nonebot
from nonebot.adapters import Bot, Event
from nonebot.compat import model_dump

from src.chatbot.settings import get_settings


STARTED_AT = datetime.now(timezone.utc)
RECENT_MESSAGES: deque["MessageRecord"] = deque(
    maxlen=get_settings().recent_message_limit
)


@dataclass(frozen=True)
class MessageRecord:
    time: str
    adapter: str
    self_id: str
    event_type: str
    detail_type: str
    session_id: str
    user_id: str
    group_id: str | None
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
    RECENT_MESSAGES.appendleft(
        MessageRecord(
            time=datetime.now(timezone.utc).isoformat(),
            adapter=bot.type,
            self_id=bot.self_id,
            event_type=_safe_call("", event.get_type),
            detail_type=detail_type,
            session_id=_safe_call("", event.get_session_id),
            user_id=_safe_call("", event.get_user_id),
            group_id=str(raw["group_id"]) if raw.get("group_id") is not None else None,
            text=text,
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
        "bots": [
            {"self_id": self_id, "adapter": bot.type}
            for self_id, bot in sorted(bots.items())
        ],
        "message_count": len(RECENT_MESSAGES),
        "qq_reverse_ws": "ws://127.0.0.1:8080/onebot/v11/ws",
        "admin": {
            "enabled": get_settings().admin_enabled,
            "token_required": bool(get_settings().admin_token),
        },
    }


def recent_messages() -> list[dict[str, Any]]:
    return [asdict(record) for record in RECENT_MESSAGES]


def get_onebot_v11_bot(self_id: str | None = None) -> Bot:
    bots = nonebot.get_bots()
    if self_id:
        bot = bots[self_id]
        if bot.type != "OneBot V11":
            raise ValueError(f"Bot {self_id} is {bot.type}, not OneBot V11")
        return bot

    for bot in bots.values():
        if bot.type == "OneBot V11":
            return bot

    raise ValueError("No OneBot V11 bot is connected yet.")


async def send_qq_message(
    *,
    target_type: str,
    target_id: int,
    message: str,
    bot_id: str | None = None,
) -> Any:
    bot = get_onebot_v11_bot(bot_id)
    if target_type == "group":
        return await bot.call_api("send_group_msg", group_id=target_id, message=message)
    if target_type == "private":
        return await bot.call_api("send_private_msg", user_id=target_id, message=message)
    raise ValueError("target_type must be 'group' or 'private'")
