from __future__ import annotations

from src.chatbot.bot_brain.local_store import LocalFactStore
from src.chatbot.bot_brain.types import BrainMemory, BrainObservation


def retrieve_memories(
    store: LocalFactStore,
    observation: BrainObservation,
    *,
    limit: int = 4,
) -> tuple[BrainMemory, ...]:
    items = list(store.list_scope(observation.scope))
    scored: list[tuple[int, BrainMemory]] = []
    for item in items:
        haystack = f"{item.topic} {item.content} {' '.join(item.tags)}".lower()
        score = sum(1 for token in observation.tokens if token and token in haystack)
        if score:
            scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    if scored:
        return tuple(item for _, item in scored[:limit])
    return tuple(items[:limit])
