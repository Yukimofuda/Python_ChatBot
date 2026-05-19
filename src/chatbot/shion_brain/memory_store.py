from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Iterable

from src.chatbot.settings import get_settings
from src.chatbot.shion_brain.models import Memory, Observation, utc_now


class SQLiteMemoryStore:
    def __init__(self, path: str | Path | None = None) -> None:
        settings = get_settings()
        self.path = Path(path or Path(settings.data_dir) / "shion_brain" / "shion.db").expanduser()

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    async def save_observation(self, observation: Observation) -> Memory:
        memory = Memory(
            id=observation.id,
            scope="group",
            scope_id=observation.group_id,
            type="short_term",
            content=observation.text,
            tags=_observation_tags(observation),
            importance=_importance(observation),
            created_at=observation.timestamp,
            last_accessed_at=observation.timestamp,
            access_count=0,
            expires_at=None,
        )
        await self.add_memory(memory)
        await self.trim_short_term(observation.group_id, get_settings().shion_max_short_messages)
        return memory

    async def add_memory(self, memory: Memory) -> None:
        await asyncio.to_thread(self._add_memory_sync, memory)

    async def search(self, scope_id: str, query: str, *, limit: int = 8) -> list[Memory]:
        return await asyncio.to_thread(self._search_sync, scope_id, query, limit)

    async def recent(self, scope_id: str, *, limit: int = 20) -> list[Memory]:
        return await asyncio.to_thread(self._recent_sync, scope_id, limit)

    async def trim_short_term(self, scope_id: str, max_items: int) -> None:
        await asyncio.to_thread(self._trim_short_term_sync, scope_id, max_items)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_sync(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    importance REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    last_accessed_at TEXT NOT NULL,
                    access_count INTEGER NOT NULL,
                    expires_at TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(scope_id, type, created_at)")

    def _add_memory_sync(self, memory: Memory) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO memories
                (id, scope, scope_id, type, content, tags, importance, created_at, last_accessed_at, access_count, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory.id,
                    memory.scope,
                    memory.scope_id,
                    memory.type,
                    memory.content,
                    json.dumps(memory.tags, ensure_ascii=False),
                    memory.importance,
                    memory.created_at,
                    memory.last_accessed_at,
                    memory.access_count,
                    memory.expires_at,
                ),
            )

    def _search_sync(self, scope_id: str, query: str, limit: int) -> list[Memory]:
        terms = [term for term in _tokens(query) if len(term) >= 2]
        rows = self._recent_sync(scope_id, 80)
        scored: list[tuple[float, Memory]] = []
        for memory in rows:
            score = memory.importance
            score += sum(1.5 for term in terms if term in memory.content)
            score += min(memory.access_count, 5) * 0.1
            if score > memory.importance:
                scored.append((score, memory))
        scored.sort(key=lambda item: item[0], reverse=True)
        selected = [memory for _, memory in scored[:limit]]
        self._touch_sync(memory.id for memory in selected)
        return selected

    def _recent_sync(self, scope_id: str, limit: int) -> list[Memory]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memories WHERE scope_id = ? ORDER BY created_at DESC LIMIT ?",
                (scope_id, limit),
            ).fetchall()
        return [_row_to_memory(row) for row in rows]

    def _trim_short_term_sync(self, scope_id: str, max_items: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM memories
                WHERE type = 'short_term'
                AND scope_id = ?
                AND id NOT IN (
                    SELECT id FROM memories
                    WHERE type = 'short_term' AND scope_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                )
                """,
                (scope_id, scope_id, max_items),
            )

    def _touch_sync(self, memory_ids: Iterable[str]) -> None:
        ids = list(memory_ids)
        if not ids:
            return
        with self._connect() as conn:
            conn.executemany(
                "UPDATE memories SET last_accessed_at = ?, access_count = access_count + 1 WHERE id = ?",
                [(utc_now(), memory_id) for memory_id in ids],
            )


def _row_to_memory(row: sqlite3.Row) -> Memory:
    return Memory(
        id=row["id"],
        scope=row["scope"],
        scope_id=row["scope_id"],
        type=row["type"],
        content=row["content"],
        tags=json.loads(row["tags"]),
        importance=float(row["importance"]),
        created_at=row["created_at"],
        last_accessed_at=row["last_accessed_at"],
        access_count=int(row["access_count"]),
        expires_at=row["expires_at"],
    )


def _observation_tags(observation: Observation) -> list[str]:
    tags = ["message"]
    tags.extend(key for key, value in observation.features.items() if value is True)
    if observation.is_command:
        tags.append("command")
    if observation.mentions_bot:
        tags.append("mention")
    return tags


def _importance(observation: Observation) -> float:
    score = 0.2
    if observation.mentions_bot:
        score += 0.4
    if observation.features.get("has_distress"):
        score += 0.2
    if observation.features.get("has_sensitive"):
        score = 0.0
    return min(1.0, score)


def _tokens(text: str) -> list[str]:
    return [part.strip().lower() for part in text.replace("，", " ").replace("。", " ").split()]


def new_memory(scope_id: str, type_: str, content: str, tags: list[str], importance: float = 0.5) -> Memory:
    now = utc_now()
    return Memory(
        id=uuid.uuid4().hex,
        scope="group",
        scope_id=scope_id,
        type=type_,
        content=content,
        tags=tags,
        importance=importance,
        created_at=now,
        last_accessed_at=now,
        access_count=0,
    )
