from __future__ import annotations

from src.chatbot.shion_brain.memory_store import SQLiteMemoryStore
from src.chatbot.shion_brain.models import Memory, Observation


class Retriever:
    def __init__(self, store: SQLiteMemoryStore) -> None:
        self.store = store

    async def retrieve(self, observation: Observation, *, limit: int = 8) -> list[Memory]:
        memories = await self.store.search(observation.group_id, observation.text, limit=limit)
        if len(memories) < min(3, limit):
            recent = await self.store.recent(observation.group_id, limit=limit)
            known = {memory.id for memory in memories}
            memories.extend(memory for memory in recent if memory.id not in known)
        return memories[:limit]


def summarize_memories(memories: list[Memory], *, max_items: int = 6) -> str:
    if not memories:
        return "暂无相关记忆"
    return "；".join(memory.content[:80] for memory in memories[:max_items])
