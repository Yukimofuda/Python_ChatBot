from __future__ import annotations

"""High-priority admin gate for natural-language memory governance.

This prevents the ordinary LLM from saying "deleted" without touching the DB.
Only explicit admin deletion/quarantine intents are handled here.
"""

import logging
import re
from typing import Any

from nonebot import on_message
from nonebot.adapters import Bot, Event
from nonebot.compat import model_dump
from nonebot.rule import Rule, to_me

from src.chatbot.message_render import truncate_text
from src.chatbot.permissions import get_user_id, require_admin
from src.chatbot.bot_brain.social_cognition import social_cognition_store
from src.chatbot.bot_brain.social_cognition.memory_governance import (
    quarantine_policy_violations,
    resolve_user_id,
    soft_delete_memories,
)
from src.chatbot.text import plain_text

logger = logging.getLogger(__name__)

DELETE_INTENT_RE = re.compile(r"(?:删除|删掉|清掉|清除|忘掉).{0,20}(?:记忆|印象|memory)", re.I | re.S)
QUARANTINE_INTENT_RE = re.compile(r"(?:隔离|治理|清洗|净化).{0,20}(?:记忆|印象|memory)", re.I | re.S)
COMMAND_PREFIX_RE = re.compile(r"^\s*[/!！]")


def _event_segments(event: Event) -> list[dict[str, Any]]:
    try:
        raw = model_dump(event)
    except Exception:
        return []
    msg = raw.get("message") or []
    return msg if isinstance(msg, list) else []


def _mentioned_user_ids(event: Event) -> list[str]:
    ids: list[str] = []
    for seg in _event_segments(event):
        if isinstance(seg, dict) and seg.get("type") == "at":
            data = seg.get("data") or {}
            qq = str(data.get("qq") or data.get("user_id") or "").strip()
            if qq and qq not in {"all"}:
                ids.append(qq)
    raw = plain_text(event)
    ids.extend(re.findall(r"\b\d{5,12}\b", raw))
    return list(dict.fromkeys(ids))


def _extract_terms(text: str) -> list[str]:
    raw = str(text or "")
    # Extract the object of deletion, e.g. “是网管的memory的记忆”, without hardcoding the value.
    patterns = (
        r"(?:是|关于|包含|含有|叫作|称作)\s*([^，。！？!?\n]{1,40}?)(?:的)?(?:记忆|印象|memory)",
        r"(?:删除|删掉|清掉|清除|忘掉)\s*([^，。！？!?\n]{1,40}?)(?:的)?(?:记忆|印象|memory)",
    )
    terms: list[str] = []
    for pat in patterns:
        for m in re.finditer(pat, raw, re.I):
            term = re.sub(r"\[CQ:[^\]]+\]", " ", m.group(1)).strip(" ：:，,。 '“”\"")
            term = re.sub(r"^@\S+\s*", "", term).strip()
            if 1 <= len(term) <= 40:
                terms.append(term)
    return list(dict.fromkeys(terms))[:5]


def _profile_governance_rule(event: Event) -> bool:
    text = plain_text(event).strip()
    if not text or COMMAND_PREFIX_RE.match(text):
        return False
    return bool(DELETE_INTENT_RE.search(text) or QUARANTINE_INTENT_RE.search(text))


memory_governance_direct = on_message(rule=to_me() & Rule(lambda event: _profile_governance_rule(event)), priority=0, block=True)


@memory_governance_direct.handle()
async def handle_memory_governance_direct(bot: Bot, event: Event) -> None:
    text = plain_text(event).strip()
    if not require_admin(event):
        await memory_governance_direct.finish("治理/删除群友记忆需要管理员权限。")

    actor = str(get_user_id(event) or "")
    mentioned = [uid for uid in _mentioned_user_ids(event) if uid != str(bot.self_id)]
    target_ref = mentioned[0] if mentioned else ""
    if not target_ref:
        # Fallback: try first platform user_id or a short reference before deletion words.
        m = re.search(r"(?:删除|删掉|清掉|清除|忘掉|隔离|治理|清洗|净化)\s*([^，。！？!?\n]{1,24})", text)
        target_ref = (m.group(1).strip() if m else "")
    uid = resolve_user_id(social_cognition_store, target_ref) if target_ref else ""
    if not uid:
        await memory_governance_direct.finish("没对上要治理哪位群友。请 @ 目标或直接给 账号 ID。")

    if QUARANTINE_INTENT_RE.search(text):
        result = quarantine_policy_violations(social_cognition_store, uid, actor_user_id=actor, dry_run=False)
        if result.get("updated"):
            reply = f"已隔离 {result['updated']} 条策略违规记忆，并写入治理审计。"
        else:
            reply = "没有发现需要隔离的 active 记忆。"
        await memory_governance_direct.finish(truncate_text(reply, 260))

    terms = _extract_terms(text)
    if not terms:
        await memory_governance_direct.finish("我能处理删除，但需要明确要删哪类记忆，例如：删除 @某人 关于 XXX 的记忆。")
    result = soft_delete_memories(
        social_cognition_store,
        uid,
        terms=terms,
        actor_user_id=actor,
        reason="admin_natural_language_memory_delete",
        dry_run=False,
    )
    if result.get("updated"):
        reply = f"已软删除 {result['updated']} 条匹配记忆，并写入治理审计。"
    else:
        reply = "没有找到匹配的 active 记忆；不会假装已经删除。"
    await memory_governance_direct.finish(truncate_text(reply, 260))
