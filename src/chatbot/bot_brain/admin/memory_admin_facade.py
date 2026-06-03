from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import uuid4

from src.chatbot.bot_brain.governance.service import DeletionPlan
from src.chatbot.bot_brain.social_arch.memory import MemorySelector, SocialMemoryService


INTERNAL_ID_RE = re.compile(r"\b\d{5,12}\b|mem_[0-9a-f]+|smem_[0-9a-f]+", re.I)


@dataclass(frozen=True)
class AdminRenderResult:
    text: str
    redacted: bool
    audit_summary: str | None
    affected_count: int
    internal_trace_id: str | None

    def public_text(self) -> str:
        return _redact(self.text)


class MemoryAdminFacade:
    """Governed admin CRUD/audit facade for P1 shadow cutover work."""

    def __init__(self, service: SocialMemoryService) -> None:
        self.service = service

    def inspect(self, selector: MemorySelector, *, actor: str = "admin", include_deleted: bool = False) -> AdminRenderResult:
        records = self.service.list_memories(MemorySelector(**{**selector.__dict__, "active": not include_deleted}), actor=actor)
        visible = [record for record in records if include_deleted or record.is_active]
        lines = [f"{_mask(record.memory_id)} {record.predicate}: {record.value_text}" for record in visible]
        text = "\n".join(lines) if lines else "没有匹配的记忆。"
        return AdminRenderResult(text=text, redacted=True, audit_summary=None, affected_count=len(visible), internal_trace_id=_trace_id())

    def list(self, selector: MemorySelector, *, actor: str = "admin", include_deleted: bool = False) -> AdminRenderResult:
        return self.inspect(selector, actor=actor, include_deleted=include_deleted)

    def preview_delete(self, selector: MemorySelector, *, actor: str = "admin") -> tuple[DeletionPlan, AdminRenderResult]:
        plan = self.service.preview_delete(selector, actor=actor)
        text = "delete preview: " + (", ".join(_mask(mid) for mid in plan.candidate_ids) if plan.candidate_ids else "empty")
        result = AdminRenderResult(text=text, redacted=True, audit_summary="preview_only", affected_count=len(plan.candidate_ids), internal_trace_id=_trace_id())
        return plan, result

    def apply_delete(self, plan: DeletionPlan, *, actor: str = "admin") -> AdminRenderResult:
        deleted = self.service.soft_delete(plan, actor=actor)
        text = f"soft_delete applied: {len(deleted)}"
        return AdminRenderResult(text=text, redacted=True, audit_summary="soft_delete", affected_count=len(deleted), internal_trace_id=_trace_id())

    def restore(self, memory_id: str, *, actor: str = "admin") -> AdminRenderResult:
        record = self.service.restore(memory_id, actor=actor)
        text = f"restore applied: {_mask(record.memory_id)}"
        return AdminRenderResult(text=text, redacted=True, audit_summary="restore", affected_count=1, internal_trace_id=_trace_id())

    def audit(self, target_id: str, *, actor: str = "admin") -> AdminRenderResult:
        logs = self.service.audit(target_id, actor=actor)
        actions = [log.action for log in logs]
        text = "audit actions: " + (", ".join(actions) if actions else "empty")
        return AdminRenderResult(text=text, redacted=True, audit_summary=",".join(actions) if actions else None, affected_count=len(logs), internal_trace_id=_trace_id())


def _mask(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    return text[:6] + "..." if len(text) > 9 else "***"


def _redact(text: str) -> str:
    return INTERNAL_ID_RE.sub("[internal]", str(text or ""))


def _trace_id() -> str:
    return f"trace_{uuid4().hex[:12]}"
