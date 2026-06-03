from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Iterable
from uuid import uuid4

from src.chatbot.bot_brain.governance.service import DeletionPlan, GovernanceDecision, MemoryGovernanceService

from .models import AuditLog, MemoryRecord


@dataclass(frozen=True)
class MemorySelector:
    identity_id: str | None = None
    scope_id: str | None = None
    memory_id: str | None = None
    predicates: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    value_contains: str | None = None
    active: bool = True


class AllowAllMemoryGovernance:
    def validate_write(self, candidate: object) -> GovernanceDecision:
        return GovernanceDecision(True, "allowed")

    def classify_read(self, request: object) -> GovernanceDecision:
        return GovernanceDecision(True, "allowed")

    def plan_delete(self, selector: object) -> DeletionPlan:
        return DeletionPlan(str(selector), (), "preview_required")

    def rollback_policy(self, action: object) -> GovernanceDecision:
        return GovernanceDecision(True, "allowed")

    def privacy_policy(self, audience: str) -> GovernanceDecision:
        return GovernanceDecision(True, "allowed")


class InMemorySocialMemoryRepository:
    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}
        self._audit: list[AuditLog] = []

    def create(self, record: MemoryRecord) -> MemoryRecord:
        self._records[record.memory_id] = record
        return record

    def update(self, memory_id: str, patch: dict, actor: str) -> MemoryRecord:
        before = self._records[memory_id]
        data = asdict(before)
        data.update(patch)
        data["updated_at"] = _now_iso()
        after = MemoryRecord(**data)
        self._records[memory_id] = after
        return after

    def list(self, identity_id: str, *, predicates: list[str] | None = None, active: bool = True) -> list[MemoryRecord]:
        selector = MemorySelector(identity_id=identity_id, predicates=tuple(predicates or ()), active=active)
        return self.retrieve(selector)

    def retrieve(self, query: object) -> list[MemoryRecord]:
        if not isinstance(query, MemorySelector):
            return []
        records = list(self._records.values())
        if query.identity_id:
            records = [record for record in records if record.identity_id == query.identity_id]
        if query.scope_id:
            records = [record for record in records if record.scope_id == query.scope_id]
        if query.memory_id:
            records = [record for record in records if record.memory_id == query.memory_id]
        if query.active:
            records = [record for record in records if record.is_active]
        if query.predicates:
            wanted = set(query.predicates)
            records = [record for record in records if record.predicate in wanted]
        if query.tags:
            wanted_tags = set(query.tags)
            records = [record for record in records if wanted_tags.intersection(record.tags)]
        if query.value_contains:
            needle = query.value_contains.casefold()
            records = [record for record in records if needle in record.value_text.casefold()]
        return sorted(records, key=lambda record: (-record.priority, -record.confidence, record.created_at))

    def soft_delete(self, memory_id: str, actor: str, reason: str) -> None:
        self.update(memory_id, {"is_active": False, "deleted_at": _now_iso()}, actor)

    def restore(self, memory_id: str, actor: str, reason: str) -> None:
        self.update(memory_id, {"is_active": True, "deleted_at": None}, actor)

    def get_audit_trail(self, target_id: str) -> list[AuditLog]:
        return [log for log in self._audit if log.target_id == target_id]

    def append_audit(self, log: AuditLog) -> None:
        self._audit.append(log)


class SocialMemoryService:
    def __init__(
        self,
        repository: InMemorySocialMemoryRepository,
        governance: MemoryGovernanceService | None = None,
    ) -> None:
        self.repository = repository
        self.governance = governance or AllowAllMemoryGovernance()

    def create_memory(self, candidate: MemoryRecord, *, actor: str, reason: str = "create") -> MemoryRecord:
        decision = self.governance.validate_write(candidate)
        if not decision.allowed:
            raise PermissionError(decision.reason)
        record = self.repository.create(candidate)
        self._audit("create", "memory", record.memory_id, actor, None, record, reason)
        return record

    def list_memories(self, selector: MemorySelector, *, actor: str = "") -> list[MemoryRecord]:
        decision = self.governance.classify_read(selector)
        if not decision.allowed:
            raise PermissionError(decision.reason)
        return self.repository.retrieve(selector)

    def preview_delete(self, selector: MemorySelector, *, actor: str, reason: str = "delete_preview") -> DeletionPlan:
        candidates = self.repository.retrieve(selector)
        ids = tuple(record.memory_id for record in candidates)
        return DeletionPlan(str(selector), ids, reason, requires_confirmation=True)

    def soft_delete(self, plan: DeletionPlan, *, actor: str, reason: str = "soft_delete") -> tuple[str, ...]:
        deleted: list[str] = []
        for memory_id in plan.candidate_ids:
            before = self.repository.retrieve(MemorySelector(memory_id=memory_id, active=False))
            before_record = before[0] if before else None
            self.repository.soft_delete(memory_id, actor, reason)
            after = self.repository.retrieve(MemorySelector(memory_id=memory_id, active=False))
            after_record = after[0] if after else None
            self._audit("soft_delete", "memory", memory_id, actor, before_record, after_record, reason)
            deleted.append(memory_id)
        return tuple(deleted)

    def restore(self, memory_id: str, *, actor: str, reason: str = "restore") -> MemoryRecord:
        decision = self.governance.rollback_policy({"memory_id": memory_id, "action": "restore"})
        if not decision.allowed:
            raise PermissionError(decision.reason)
        before = self.repository.retrieve(MemorySelector(memory_id=memory_id, active=False))
        before_record = before[0] if before else None
        self.repository.restore(memory_id, actor, reason)
        after = self.repository.retrieve(MemorySelector(memory_id=memory_id, active=False))
        record = after[0]
        self._audit("restore", "memory", memory_id, actor, before_record, record, reason)
        return record

    def audit(self, target_id: str, *, actor: str = "") -> list[AuditLog]:
        return self.repository.get_audit_trail(target_id)

    def _audit(
        self,
        action: str,
        target_type: str,
        target_id: str,
        actor: str,
        before: MemoryRecord | None,
        after: MemoryRecord | None,
        reason: str,
    ) -> None:
        self.repository.append_audit(
            AuditLog(
                audit_id=f"audit_{uuid4().hex}",
                action=action,
                target_type=target_type,
                target_id=target_id,
                actor_internal_id=actor or None,
                actor_role="system" if not actor else "operator",
                before_json=_record_json(before),
                after_json=_record_json(after),
                reason=reason,
                correlation_id=f"corr_{uuid4().hex}",
                created_at=_now_iso(),
            )
        )


def make_memory_record(
    *,
    memory_id: str | None = None,
    identity_id: str,
    scope_id: str,
    predicate: str,
    value_text: str,
    evidence_text: str = "",
    source_type: str = "system_migration",
    source_identity_id: str | None = None,
    confidence: float = 0.5,
    priority: float = 0.5,
    tags: Iterable[str] = (),
) -> MemoryRecord:
    now = _now_iso()
    return MemoryRecord(
        memory_id=memory_id or f"mem_{uuid4().hex}",
        identity_id=identity_id,
        scope_id=scope_id,
        predicate=predicate,
        value_text=value_text,
        evidence_text=evidence_text,
        source_type=source_type,
        source_identity_id=source_identity_id,
        confidence=confidence,
        priority=priority,
        tags=tuple(tags),
        valid_from=None,
        valid_to=None,
        is_active=True,
        render_policy="public_summary",
        created_at=now,
        updated_at=now,
    )


def _record_json(record: MemoryRecord | None) -> str:
    if record is None:
        return "{}"
    return json.dumps(asdict(record), ensure_ascii=False, sort_keys=True)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
