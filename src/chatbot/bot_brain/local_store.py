from __future__ import annotations

from dataclasses import dataclass, field

from src.chatbot.bot_brain.types import BrainMemory


@dataclass
class LocalFactStore:
    _items: dict[str, list[BrainMemory]] = field(default_factory=dict)

    def add(self, memory: BrainMemory) -> None:
        self._items.setdefault(memory.scope, []).append(memory)

    def list_scope(self, scope: str) -> tuple[BrainMemory, ...]:
        return tuple(self._items.get(scope, ()))

    def clear_scope(self, scope: str) -> None:
        self._items.pop(scope, None)

    def stats(self) -> dict[str, int]:
        return {scope: len(items) for scope, items in self._items.items()}
