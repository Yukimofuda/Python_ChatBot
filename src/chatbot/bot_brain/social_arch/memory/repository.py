from __future__ import annotations

from typing import Protocol

from .models import AuditLog, MemoryRecord


class SocialMemoryRepository(Protocol):
    def create(self, record: MemoryRecord) -> MemoryRecord:
        ...

    def update(self, memory_id: str, patch: dict, actor: str) -> MemoryRecord:
        ...

    def list(self, identity_id: str, *, predicates: list[str] | None = None, active: bool = True) -> list[MemoryRecord]:
        ...

    def retrieve(self, query: object) -> list[MemoryRecord]:
        ...

    def soft_delete(self, memory_id: str, actor: str, reason: str) -> None:
        ...

    def restore(self, memory_id: str, actor: str, reason: str) -> None:
        ...

    def get_audit_trail(self, target_id: str) -> list[AuditLog]:
        ...

