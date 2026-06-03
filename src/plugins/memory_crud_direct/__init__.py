from __future__ import annotations

"""High-priority command gate for auditable social memory CRUD.

Supported commands:
  /memory add <账号ID|昵称> <记忆内容> [#alias|#nickname|#profile]
  /memory list <账号ID|昵称> [--all]
  /memory edit <memory_id> <新内容> [#tags]
  /memory delete <memory_id>
  /memory delete <账号ID|昵称> <匹配词>
  /memory restore <memory_id>
  /memory audit [memory_id|账号ID|昵称]

All write actions require admin permission and go through SocialMemoryCrud.
"""

import re
from typing import Any

from nonebot import on_message
from nonebot.adapters import Event
from nonebot.rule import Rule

from src.chatbot.message_render import truncate_text
from src.chatbot.permissions import get_user_id, require_admin
from src.chatbot.bot_brain.social_cognition.tasks import (
    format_memory_add,
    format_memory_audit,
    format_memory_delete,
    format_memory_list,
    format_memory_restore,
    format_memory_update,
)
from src.chatbot.text import plain_text

MEMORY_CRUD_RE = re.compile(r"^\s*/memory\s+(?:add|list|edit|update|delete|del|remove|restore|audit)\b", re.I)
TAG_RE = re.compile(r"#([A-Za-z0-9_\-\u4e00-\u9fff]{1,32})")


def _rule(event: Event) -> bool:
    return bool(MEMORY_CRUD_RE.match(plain_text(event).strip()))


def _strip_tags(text: str) -> tuple[str, str]:
    tags = TAG_RE.findall(text or "")
    clean = TAG_RE.sub("", text or "").strip()
    return clean, " ".join(tags) if tags else "profile"


def _split2(rest: str) -> tuple[str, str]:
    parts = str(rest or "").strip().split(maxsplit=1)
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


memory_crud_direct = on_message(rule=Rule(lambda event: _rule(event)), priority=0, block=True)


@memory_crud_direct.handle()
async def handle_memory_crud_direct(event: Event) -> None:
    text = plain_text(event).strip()
    m = re.match(r"^\s*/memory\s+(add|list|edit|update|delete|del|remove|restore|audit)\b\s*(.*)$", text, re.I | re.S)
    if not m:
        return
    op = m.group(1).casefold()
    rest = (m.group(2) or "").strip()
    actor = str(get_user_id(event) or "")

    write_ops = {"add", "edit", "update", "delete", "del", "remove", "restore"}
    if op in write_ops and not require_admin(event):
        await memory_crud_direct.finish("新增/修改/删除群友记忆需要管理员权限。")

    try:
        if op == "add":
            ref, payload = _split2(rest)
            payload, tags = _strip_tags(payload)
            if not ref or not payload:
                reply = "用法：/memory add <账号ID或昵称> <记忆内容> [#alias|#nickname|#profile]"
            else:
                reply = format_memory_add(ref, payload, tags=tags, actor_user_id=actor)
        elif op == "list":
            ref, flags = _split2(rest)
            if not ref:
                reply = "用法：/memory list <账号ID或昵称> [--all]"
            else:
                reply = format_memory_list(ref, include_hidden="--all" in flags)
        elif op in {"edit", "update"}:
            mid, payload = _split2(rest)
            payload, tags = _strip_tags(payload)
            if not mid or not payload:
                reply = "用法：/memory edit <memory_id> <新内容> [#alias|#nickname|#profile]"
            else:
                explicit_tags = tags if TAG_RE.search(rest) else None
                reply = format_memory_update(mid, payload, tags=explicit_tags, actor_user_id=actor)
        elif op in {"delete", "del", "remove"}:
            ref, term = _split2(rest)
            if not ref:
                reply = "用法：/memory delete <memory_id> 或 /memory delete <账号ID或昵称> <匹配词>"
            else:
                reply = format_memory_delete(ref, term, actor_user_id=actor)
        elif op == "restore":
            if not rest:
                reply = "用法：/memory restore <memory_id>"
            else:
                reply = format_memory_restore(rest.split()[0], actor_user_id=actor)
        elif op == "audit":
            reply = format_memory_audit(rest)
        else:
            reply = "未知 memory CRUD 命令。"
    except Exception as exc:  # pragma: no cover - live safety net
        reply = f"memory CRUD 执行失败：{type(exc).__name__}: {exc}"
    await memory_crud_direct.finish(truncate_text(reply, 900))
