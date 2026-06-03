from __future__ import annotations

"""High-priority live gate for platform-user social profile memory queries.

This plugin is intentionally small at the live boundary: it only decides whether
an @Bot message is a profile/identity/enumeration query, then delegates target
resolution and answer construction to the structured memory-decision/profile
answerer stack. It must stay ahead of ordinary persona/LLM plugins.
"""

import dataclasses
import logging
import os
import re
from typing import Any

from nonebot import on_message
from nonebot.adapters import Bot, Event
from nonebot.compat import model_dump
from nonebot.rule import Rule, to_me

from src.chatbot.message_render import truncate_text
from src.chatbot.permissions import get_user_id
from src.chatbot.bot_brain import event_to_observation
from src.chatbot.bot_brain.memory_decision_frame import BOT_SELF_QUERY_RE, build_memory_decision_frame, strip_bot_mentions
from src.chatbot.bot_brain.social_cognition.profile_answerer import answer_profile_memory_query_result, is_profile_memory_query
from src.chatbot.text import plain_text

logger = logging.getLogger(__name__)
COMMAND_RE = re.compile(r"^\s*[/!！]")


def _reply_segment_id(event: Event) -> str:
    try:
        raw = model_dump(event)
    except Exception:
        return ""
    message = raw.get("message") or []
    if isinstance(message, list):
        for seg in message:
            if isinstance(seg, dict) and seg.get("type") == "reply":
                data = seg.get("data") or {}
                return str(data.get("id") or data.get("message_id") or "").strip()
    raw_message = str(raw.get("raw_message") or raw.get("message") or "")
    m = re.search(r"\[CQ:reply,id=([^,\]]+)", raw_message)
    return m.group(1).strip() if m else ""


def _message_plain(message: Any) -> str:
    if isinstance(message, list):
        parts: list[str] = []
        for seg in message:
            if isinstance(seg, dict):
                typ = seg.get("type")
                data = seg.get("data") or {}
                if typ == "text":
                    parts.append(str(data.get("text") or ""))
                elif typ == "at":
                    parts.append("@" + str(data.get("name") or data.get("qq") or ""))
        return "".join(parts).strip()
    return str(message or "").strip()


async def _fetch_reply_context(bot: Bot, event: Event) -> dict[str, str]:
    reply_id = _reply_segment_id(event)
    if not reply_id:
        return {}
    try:
        msg = await bot.call_api("get_msg", message_id=int(reply_id) if str(reply_id).isdigit() else reply_id)
    except Exception:
        logger.debug("profile_memory_direct: failed to fetch replied message id=%s", reply_id, exc_info=True)
        return {"reply_message_id": str(reply_id)}
    if not isinstance(msg, dict):
        return {"reply_message_id": str(reply_id)}
    sender = msg.get("sender") or {}
    uid = str(msg.get("user_id") or sender.get("user_id") or "").strip()
    name = str(sender.get("card") or sender.get("nickname") or sender.get("name") or "").strip()
    text = _message_plain(msg.get("message") or msg.get("raw_message") or "")
    return {
        "reply_message_id": str(reply_id),
        "reply_user_id": uid,
        "reply_sender_id": uid,
        "replied_user_id": uid,
        "reply_sender_display_name": name,
        "reply_display_name": name,
        "replied_sender_display_name": name,
        "reply_message_text": text,
        "replied_message_text": text,
    }


async def _observation_with_live_context(bot: Bot, event: Event):
    observation = event_to_observation(bot, event)
    extra = await _fetch_reply_context(bot, event)
    features = dict(getattr(observation, "features", {}) or {})
    if extra:
        features.update({k: v for k, v in extra.items() if v})
    # Mark that NoneBot to_me() already accepted this event. Do NOT use this as
    # the only condition for routing; it is debug evidence for the decision frame.
    features.setdefault("live_to_me", True)
    try:
        return dataclasses.replace(observation, features=features)
    except Exception:
        return observation


def _debug_enabled() -> bool:
    return str(os.getenv("BOT_MEMORY_DECISION_DEBUG") or "").strip().lower() in {"1", "true", "yes", "on"}


def _log_decision(prefix: str, observation: Any, *, handled: bool | None = None, reply: str = "") -> None:
    if not _debug_enabled():
        return
    try:
        frame = build_memory_decision_frame(observation)
        logger.info(
            "%s handled=%s intent=%s search_memory=%s target=%s aliases=%s text=%r reply=%r",
            prefix,
            handled,
            frame.intent,
            frame.search_memory,
            frame.target.kind,
            frame.target.alias_terms,
            getattr(observation, "text", ""),
            reply,
        )
    except Exception:
        logger.debug("profile_memory_direct decision log failed", exc_info=True)


async def _profile_memory_rule(bot: Bot, event: Event) -> bool:
    try:
        if str(get_user_id(event)) == str(bot.self_id):
            return False
        raw_text = plain_text(event).strip()
        normalized_text = strip_bot_mentions(raw_text)
        if not normalized_text or COMMAND_RE.match(normalized_text):
            return False
        # Bot self-query must not be consumed by social profile memory. Let the
        # normal persona self-introduction chain answer it.
        if BOT_SELF_QUERY_RE.match(normalized_text):
            return False

        observation = await _observation_with_live_context(bot, event)
        # Important invariant: NoneBot's to_me() is the live mention gate. Do not
        # require the Observation bot-mention boolean here, because event_to_observation may
        # lose that flag after CQ/at normalization. This was the failure mode
        # where inspect_social_alias.py found 小学弟, but live still fell through
        # to ordinary LLM and hallucinated.
        handled = bool(is_profile_memory_query(observation))
        _log_decision("profile_memory_direct.rule", observation, handled=handled)
        return handled
    except Exception:
        logger.exception("profile_memory_direct rule failed")
        return False


# priority=0 keeps this gate ahead of ordinary persona/ambient/core LLM plugins.
# block=True is critical: once an identity/profile query is handled or safe-
# fallbacked, it must never fall through to the ordinary LLM.
profile_memory_direct = on_message(rule=to_me() & Rule(_profile_memory_rule), priority=0, block=True)


@profile_memory_direct.handle()
async def handle_profile_memory_direct(bot: Bot, event: Event) -> None:
    try:
        observation = await _observation_with_live_context(bot, event)
        result = answer_profile_memory_query_result(observation, max_length=520)
        reply = result.reply if result.handled else ""
        _log_decision("profile_memory_direct.answer", observation, handled=result.handled, reply=reply)
    except Exception:
        logger.exception("profile_memory_direct answer failed")
        reply = "嗯…我刚才想对一下群友记忆但卡住了。你 @ 一下那个人，我就能继续接上。"
    if not reply:
        # This branch should be rare. Since the matcher already consumed a strict
        # profile-memory query, always safe-fallback here instead of releasing the
        # event to ordinary LLM.
        reply = "嗯…这个人我暂时没对上是谁，别让我乱猜啦。你 @ 一下或者回复他的消息我就能接上。"
    await profile_memory_direct.finish(truncate_text(reply, 560))
