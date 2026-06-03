from __future__ import annotations

"""Natural-language memory CRUD gate for admin-bound Bot operators.

Examples:
  @Bot 把@群友Q关于 ph 的记忆删掉
  @Bot 给@群友Q加一条记忆：喜欢 Python 和修 bot
  @Bot 把@群友Q关于 Python 的记忆改成喜欢 Rust

The plugin parses a typed action plan, checks bound-admin permission, and calls
SocialMemoryCrud. It never answers “done” unless the DB operation returned ok.
"""

import re
from typing import Iterable

from nonebot import on_message
from nonebot.adapters import Event
from nonebot.rule import Rule, to_me

from src.chatbot.message_render import truncate_text
from src.chatbot.permissions import get_user_id, require_admin
from src.chatbot.bot_brain.social_cognition.natural_memory_crud import (
    execute_natural_memory_action,
    is_bound_memory_admin,
    parse_natural_memory_request,
)
from src.chatbot.bot_brain.social_cognition.store import social_cognition_store
from src.chatbot.text import plain_text

CQ_AT_RE = re.compile(r"\[CQ:at,qq=(\d{5,12})\]")


def _extract_group_id(event: Event) -> str:
    for name in ("group_id", "guild_id"):
        try:
            value = getattr(event, name, "")
            if value:
                return str(value)
        except Exception:
            pass
    try:
        sid = event.get_session_id()
        m = re.search(r"group_(\d+)_", sid)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


def _extract_mentioned_user_ids(event: Event) -> list[str]:
    ids: list[str] = []
    try:
        message = event.get_message()
        for seg in message:
            if getattr(seg, "type", "") == "at":
                qq = str(getattr(seg, "data", {}).get("qq", "")).strip()
                if qq and qq != "all":
                    ids.append(qq)
        raw = str(message)
    except Exception:
        raw = ""
    for qq in CQ_AT_RE.findall(raw):
        if qq not in ids:
            ids.append(qq)
    return ids


def _rule(event: Event) -> bool:
    text = plain_text(event).strip()
    mentions = _extract_mentioned_user_ids(event)
    return parse_natural_memory_request(text, mentioned_user_ids=mentions) is not None


memory_nl_crud_direct = on_message(rule=to_me() & Rule(lambda event: _rule(event)), priority=0, block=True)


@memory_nl_crud_direct.handle()
async def handle_memory_nl_crud_direct(event: Event) -> None:
    actor = str(get_user_id(event) or "")
    if not is_bound_memory_admin(actor, require_admin_result=require_admin(event)):
        await memory_nl_crud_direct.finish("这类记忆操作只有绑定账号能做。")

    text = plain_text(event).strip()
    mentions = _extract_mentioned_user_ids(event)
    action = parse_natural_memory_request(text, mentioned_user_ids=mentions)
    if action is None:
        return
    if action.confidence < 0.7 or not action.executable:
        await memory_nl_crud_direct.finish("这句还不够明确：需要指定群友，以及要新增/修改/删除的记忆内容。")

    result = execute_natural_memory_action(
        social_cognition_store,
        action,
        actor_user_id=actor,
        scope_id=_extract_group_id(event),
    )
    await memory_nl_crud_direct.finish(truncate_text(result.reply, 500))
