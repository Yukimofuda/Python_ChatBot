from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    identity_id: str
    scope_id: str
    predicate: str
    value_text: str
    evidence_text: str
    source_type: str
    source_identity_id: str | None
    confidence: float
    priority: float
    tags: tuple[str, ...]
    valid_from: str | None
    valid_to: str | None
    is_active: bool
    render_policy: str
    created_at: str
    updated_at: str
    deleted_at: str | None = None


@dataclass(frozen=True)
class AuditLog:
    audit_id: str
    action: str
    target_type: str
    target_id: str
    actor_internal_id: str | None
    actor_role: str
    before_json: str
    after_json: str
    reason: str
    correlation_id: str
    created_at: str

