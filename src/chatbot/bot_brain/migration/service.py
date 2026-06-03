from __future__ import annotations

from typing import Protocol


class MemoryMigrationService(Protocol):
    def snapshot(self) -> str:
        ...

    def backfill(self) -> dict[str, int]:
        ...

    def shadow_read_compare(self) -> dict[str, int]:
        ...

    def cutover_ready(self) -> bool:
        ...

