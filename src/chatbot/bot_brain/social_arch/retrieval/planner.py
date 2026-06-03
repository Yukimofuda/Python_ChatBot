from __future__ import annotations

from typing import Protocol


class RetrievalPlanner(Protocol):
    def plan(self, query: object) -> object:
        ...


class MemoryRetriever(Protocol):
    def retrieve(self, plan: object) -> list[object]:
        ...

