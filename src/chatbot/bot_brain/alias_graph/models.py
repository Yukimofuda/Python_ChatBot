from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AliasNode:
    alias_id: str
    identity_id: str
    alias_value: str
    alias_norm: str
    alias_type: str
    scope_id: str
    source_memory_id: str | None
    confidence: float
    active: bool
    created_at: str
    updated_at: str

