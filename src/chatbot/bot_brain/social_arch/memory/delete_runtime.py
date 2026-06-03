from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.chatbot.bot_brain.governance.service import DeletionPlan
from src.chatbot.bot_brain.social_arch.identity_facade import SocialIdentityFacade

from .service import MemorySelector, SocialMemoryService


@dataclass(frozen=True)
class DeleteRuntimeResult:
    preview: DeletionPlan
    deleted_ids: tuple[str, ...] = ()
    reply: str = ""
    admin_reply: str = ""


class MemoryDeleteRuntime:
    """Governed delete flow for social memory runtime cutover.

    All deletes are previewed first. Subject identity comes from explicit
    mention/reply/alias resolution; the free-form delete term only filters
    already-selected memories.
    """

    def __init__(self, service: SocialMemoryService, identity_facade: SocialIdentityFacade) -> None:
        self.service = service
        self.identity_facade = identity_facade

    def preview(self, *, identity_id: str, value_contains: str = "", predicates: tuple[str, ...] = (), tags: tuple[str, ...] = (), actor: str = "") -> DeleteRuntimeResult:
        selector = MemorySelector(
            identity_id=identity_id,
            predicates=predicates,
            tags=tags,
            value_contains=value_contains or None,
            active=True,
        )
        plan = self.service.preview_delete(selector, actor=actor)
        reply = "没有找到要删除的记忆。" if not plan.candidate_ids else f"将删除 {len(plan.candidate_ids)} 条匹配记忆，请确认。"
        admin_reply = self._admin_preview(plan)
        return DeleteRuntimeResult(preview=plan, reply=reply, admin_reply=admin_reply)

    def apply(self, plan: DeletionPlan, *, actor: str = "") -> DeleteRuntimeResult:
        if not plan.candidate_ids:
            return DeleteRuntimeResult(preview=plan, reply="没有找到要删除的记忆。", admin_reply="delete preview empty")
        deleted = self.service.soft_delete(plan, actor=actor)
        reply = f"已删除 {len(deleted)} 条匹配记忆。"
        admin_reply = "soft_delete audit=" + ",".join(_mask_memory_id(mid) for mid in deleted)
        return DeleteRuntimeResult(preview=plan, deleted_ids=deleted, reply=reply, admin_reply=admin_reply)

    def preview_from_observation(self, observation: Any, *, value_contains: str = "", actor: str = "") -> DeleteRuntimeResult:
        identity_id = self._identity_from_observation(observation)
        if not identity_id:
            empty = DeletionPlan("unresolved_identity", (), "identity_required", requires_confirmation=True)
            return DeleteRuntimeResult(preview=empty, reply="需要先明确要删除哪位群友的记忆。", admin_reply="identity unresolved")
        return self.preview(identity_id=identity_id, value_contains=value_contains, actor=actor)

    def _identity_from_observation(self, observation: Any) -> str:
        mentioned = list(getattr(observation, "mentioned_user_ids", None) or (getattr(observation, "features", {}) or {}).get("mentioned_user_ids") or [])
        features = getattr(observation, "features", {}) or {}
        bot_ids = {str(features.get(k) or "") for k in ("bot_id", "self_id", "bot_self_id")}
        sender = str(getattr(observation, "sender_id", "") or getattr(observation, "user_id", "") or "")
        targets = [str(uid) for uid in mentioned if str(uid) and str(uid) != sender and str(uid) not in bot_ids]
        if len(targets) == 1:
            return str(self.identity_facade.resolve_mention(observation, targets[0]).result.identity_id or "")
        return ""

    @staticmethod
    def _admin_preview(plan: DeletionPlan) -> str:
        if not plan.candidate_ids:
            return "preview empty"
        return "preview " + ",".join(_mask_memory_id(mid) for mid in plan.candidate_ids)


def _mask_memory_id(memory_id: str) -> str:
    text = str(memory_id or "")
    if len(text) <= 8:
        return "[id]"
    return re.sub(r"^(.{4}).*(.{4})$", r"\1...\2", text)
