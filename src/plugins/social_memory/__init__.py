from __future__ import annotations

from nonebot import logger, on_command, on_message
from nonebot.adapters import Bot, Event
from nonebot.params import CommandArg
from nonebot.compat import model_dump

from src.chatbot.permissions import get_user_id, require_admin
from src.chatbot.bot_brain import event_to_observation
from src.chatbot.bot_brain.social_cognition import social_cognition_store
from src.chatbot.bot_brain.social_cognition.tasks import (
    format_add,
    format_audit,
    format_delete,
    format_edit,
    format_events,
    format_inspect,
    format_list,
    format_restore,
    format_status,
)
from src.chatbot.text import plain_text

observer = on_message(priority=75, block=False)
memory_cmd = on_command("memory", priority=0, block=True)


def _scope_id(event: Event) -> str:
    for name in ("group_id", "guild_id"):
        try:
            value = getattr(event, name, "")
            if value:
                return str(value)
        except Exception:
            pass
    try:
        sid = event.get_session_id()
        import re
        m = re.search(r"group_(\d+)_", sid)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


def _mentioned_user_ids(event: Event, *, bot_self_id: str = "") -> list[str]:
    """Return platform user_ids mentioned in this command, excluding the bot account.

    CommandArg.extract_plain_text() may drop `at` segments, so /memory list @A
    must resolve targets from raw message segments, not from plain text alone.
    """
    ids: list[str] = []
    try:
        raw = model_dump(event)
    except Exception:
        raw = {}
    message = raw.get("message") or []
    if isinstance(message, list):
        for seg in message:
            if isinstance(seg, dict) and seg.get("type") == "at":
                qq = str((seg.get("data") or {}).get("qq") or "").strip()
                if qq and qq != str(bot_self_id) and qq not in ids:
                    ids.append(qq)
    raw_message = str(raw.get("raw_message") or "")
    import re
    for qq in re.findall(r"\[CQ:at,qq=(\d{5,12})\]", raw_message):
        if qq and qq != str(bot_self_id) and qq not in ids:
            ids.append(qq)
    return ids


@observer.handle()
async def observe_social_cognition(bot: Bot, event: Event) -> None:
    text = plain_text(event).strip()
    if not text or text.lstrip().startswith(("/", "!", "！")):
        return
    try:
        observation = event_to_observation(bot, event)
        social_cognition_store.record_observation(observation)
    except Exception:
        logger.exception("social_cognition observer failed")


@memory_cmd.handle()
async def handle_memory_command(event: Event, args=CommandArg()) -> None:
    raw = args.extract_plain_text().strip()
    command, _, rest = raw.partition(" ")
    command = command.strip().lower()
    rest = rest.strip()
    actor = str(get_user_id(event) or "")
    mention_ids = _mentioned_user_ids(event)
    subject_hint = mention_ids[0] if mention_ids else ""

    if command in {"", "status"}:
        await memory_cmd.finish(format_status())

    if command in {"inspect", "who", "profile", "查"}:
        await memory_cmd.finish(format_inspect(rest, subject_hint=subject_hint))

    if command in {"list", "ls"}:
        await memory_cmd.finish(format_list(rest, include_hidden="--all" in rest or "—all" in rest or "–all" in rest, subject_hint=subject_hint))

    if command in {"events", "event"}:
        await memory_cmd.finish(format_events(rest))

    if command in {"add", "create", "新增", "添加", "记住"}:
        if not require_admin(event):
            await memory_cmd.finish("这类记忆操作需要管理员权限。")
        await memory_cmd.finish(format_add(rest, actor_user_id=actor, scope_id=_scope_id(event), subject_hint=subject_hint))

    if command in {"edit", "update", "修改", "改"}:
        if not require_admin(event):
            await memory_cmd.finish("这类记忆操作需要管理员权限。")
        await memory_cmd.finish(format_edit(rest, actor_user_id=actor))

    if command in {"forget", "delete", "清除", "删", "删除"}:
        if not require_admin(event):
            await memory_cmd.finish("这类记忆操作需要管理员权限。")
        await memory_cmd.finish(format_delete(rest, actor_user_id=actor, subject_hint=subject_hint))

    if command in {"restore", "undo", "恢复", "还原"}:
        if not require_admin(event):
            await memory_cmd.finish("这类记忆操作需要管理员权限。")
        await memory_cmd.finish(format_restore(rest, actor_user_id=actor, subject_hint=subject_hint))

    if command in {"audit", "history", "log", "记录"}:
        await memory_cmd.finish(format_audit(rest))

    await memory_cmd.finish(
        "用法：/memory status、/memory inspect <账号ID或昵称>、/memory list <账号ID或昵称> [--all]、"
        "/memory add <账号ID或昵称> <记忆内容> [#profile|#alias]、/memory edit <memory_id> <新内容>、"
        "/memory delete <memory_id|账号ID 关键词>、/memory restore <memory_id|账号ID 关键词>、/memory audit <memory_id|QQ>"
    )
