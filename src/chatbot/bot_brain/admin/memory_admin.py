from __future__ import annotations

from typing import Protocol


class MemoryAdminService(Protocol):
    def inspect(self, reference: str, actor_role: str) -> str:
        ...

    def list(self, selector: object, actor_role: str) -> str:
        ...

    def delete(self, selector: object, actor_role: str) -> str:
        ...

    def restore(self, selector: object, actor_role: str) -> str:
        ...

    def audit(self, selector: object, actor_role: str) -> str:
        ...

