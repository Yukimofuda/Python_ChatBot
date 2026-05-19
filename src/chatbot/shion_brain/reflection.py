from __future__ import annotations

from collections import Counter

from src.chatbot.shion_brain.memory_store import SQLiteMemoryStore, new_memory


class ReflectionEngine:
    def __init__(self, store: SQLiteMemoryStore) -> None:
        self.store = store

    async def reflect_group(self, group_id: str) -> str:
        recent = await self.store.recent(group_id, limit=80)
        if not recent:
            return "最近没有足够消息生成反思。"
        words = Counter()
        for memory in recent:
            for token in memory.content.replace("，", " ").replace("。", " ").split():
                if len(token) >= 2:
                    words[token] += 1
        top = "、".join(word for word, _ in words.most_common(8)) or "暂无"
        summary = f"群聊反思：最近消息 {len(recent)} 条；高频词：{top}。"
        await self.store.add_memory(new_memory(group_id, "reflection", summary, ["reflection"], 0.7))
        return summary
