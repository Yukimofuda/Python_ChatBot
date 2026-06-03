from __future__ import annotations

import asyncio
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone
from typing import Literal

from src.chatbot.settings import get_settings
from src.chatbot.bot_brain.critic import contains_sensitive
from src.chatbot.bot_brain.models import utc_now


ThoughtType = Literal["reflection", "followup", "repair", "curiosity", "task"]
ThoughtStatus = Literal["pending", "incubating", "locked", "done", "dismissed"]


@dataclass(frozen=True)
class Thought:
    id: str
    scope_id: str
    user_id: str | None
    type: ThoughtType
    content: str
    priority: float
    status: ThoughtStatus
    created_at: str
    due_at: str | None
    source_observation_id: str | None


class ThoughtQueue:
    def __init__(self, path: str | Path | None = None) -> None:
        settings = get_settings()
        self.path = Path(path or Path(settings.data_dir) / "bot_brain" / "bot.db").expanduser()

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    async def create_thought(
        self,
        *,
        scope_id: str,
        type: ThoughtType,
        content: str,
        user_id: str | None = None,
        priority: float = 0.5,
        due_at: str | None = None,
        source_observation_id: str | None = None,
        status: ThoughtStatus = "pending",
    ) -> Thought | None:
        if not content.strip() or contains_sensitive(content):
            return None
        thought = Thought(
            id=uuid.uuid4().hex,
            scope_id=scope_id,
            user_id=user_id,
            type=type,
            content=content.strip()[:500],
            priority=min(1.0, max(0.0, priority)),
            status=status,
            created_at=utc_now(),
            due_at=due_at,
            source_observation_id=source_observation_id,
        )
        await asyncio.to_thread(self._insert_sync, thought)
        return thought

    async def list_pending_thoughts(self, scope_id: str, limit: int = 5) -> list[Thought]:
        return await asyncio.to_thread(self._list_pending_sync, scope_id, limit)

    async def list_incubating_thoughts(self, min_age_minutes: int = 30, limit: int = 8) -> list[Thought]:
        return await asyncio.to_thread(self._list_incubating_sync, min_age_minutes, limit)

    async def mark_thought_incubating(self, thought_id: str) -> None:
        await asyncio.to_thread(self._set_status_sync, thought_id, "incubating")

    async def mark_thought_locked(self, thought_id: str) -> None:
        await asyncio.to_thread(self._set_status_sync, thought_id, "locked")

    async def mark_thought_done(self, thought_id: str) -> None:
        await asyncio.to_thread(self._set_status_sync, thought_id, "done")

    async def dismiss_thought(self, thought_id: str) -> None:
        await asyncio.to_thread(self._set_status_sync, thought_id, "dismissed")

    async def raise_priority_for_repair(self, scope_id: str, user_id: str | None = None) -> None:
        await asyncio.to_thread(self._raise_priority_for_repair_sync, scope_id, user_id)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def _initialize_sync(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS thoughts (
                    id TEXT PRIMARY KEY,
                    scope_id TEXT NOT NULL,
                    user_id TEXT,
                    type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    priority REAL NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    due_at TEXT,
                    source_observation_id TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_thoughts_pending ON thoughts(scope_id, status, priority, created_at)")

    def _insert_sync(self, thought: Thought) -> None:
        self._initialize_sync()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO thoughts
                (id, scope_id, user_id, type, content, priority, status, created_at, due_at, source_observation_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    thought.id,
                    thought.scope_id,
                    thought.user_id,
                    thought.type,
                    thought.content,
                    thought.priority,
                    thought.status,
                    thought.created_at,
                    thought.due_at,
                    thought.source_observation_id,
                ),
            )

    def _list_pending_sync(self, scope_id: str, limit: int) -> list[Thought]:
        self._initialize_sync()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM thoughts
                WHERE scope_id = ? AND status IN ('pending', 'incubating')
                ORDER BY priority DESC, created_at DESC
                LIMIT ?
                """,
                (scope_id, limit),
            ).fetchall()
        return [_row_to_thought(row) for row in rows]

    def _list_incubating_sync(self, min_age_minutes: int, limit: int) -> list[Thought]:
        self._initialize_sync()
        cutoff = datetime.now(timezone.utc).timestamp() - min_age_minutes * 60
        cutoff_iso = datetime.fromtimestamp(cutoff, timezone.utc).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM thoughts
                WHERE status = 'incubating'
                  AND created_at <= ?
                ORDER BY priority DESC, created_at ASC
                LIMIT ?
                """,
                (cutoff_iso, limit),
            ).fetchall()
        return [_row_to_thought(row) for row in rows]

    def _set_status_sync(self, thought_id: str, status: ThoughtStatus) -> None:
        self._initialize_sync()
        with self._connect() as conn:
            conn.execute("UPDATE thoughts SET status = ? WHERE id = ?", (status, thought_id))

    def _raise_priority_for_repair_sync(self, scope_id: str, user_id: str | None) -> None:
        self._initialize_sync()
        params: tuple[object, ...]
        where = "scope_id = ? AND status = 'pending' AND type = 'repair'"
        params = (scope_id,)
        if user_id is not None:
            where += " AND (user_id = ? OR user_id IS NULL)"
            params = (scope_id, user_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE thoughts SET priority = MIN(priority + 0.2, 1.0) WHERE {where}",
                params,
            )


_default_queue = ThoughtQueue()


async def create_thought(**kwargs) -> Thought | None:
    await _default_queue.initialize()
    return await _default_queue.create_thought(**kwargs)


async def list_pending_thoughts(scope_id: str, limit: int = 5) -> list[Thought]:
    await _default_queue.initialize()
    return await _default_queue.list_pending_thoughts(scope_id, limit=limit)


async def list_incubating_thoughts(min_age_minutes: int = 30, limit: int = 8) -> list[Thought]:
    await _default_queue.initialize()
    return await _default_queue.list_incubating_thoughts(min_age_minutes=min_age_minutes, limit=limit)


async def mark_thought_incubating(thought_id: str) -> None:
    await _default_queue.initialize()
    await _default_queue.mark_thought_incubating(thought_id)


async def mark_thought_locked(thought_id: str) -> None:
    await _default_queue.initialize()
    await _default_queue.mark_thought_locked(thought_id)


async def mark_thought_done(thought_id: str) -> None:
    await _default_queue.initialize()
    await _default_queue.mark_thought_done(thought_id)


async def dismiss_thought(thought_id: str) -> None:
    await _default_queue.initialize()
    await _default_queue.dismiss_thought(thought_id)


async def raise_priority_for_repair(scope_id: str, user_id: str | None = None) -> None:
    await _default_queue.initialize()
    await _default_queue.raise_priority_for_repair(scope_id, user_id)


def summarize_thoughts(thoughts: list[Thought], *, max_items: int = 4) -> str:
    if not thoughts:
        return "暂无未完成的内部想法。"
    lines = []
    for thought in thoughts[:max_items]:
        lines.append(_thought_hint(thought))
    return "；".join(lines)


def _thought_hint(thought: Thought) -> str:
    if thought.type == "repair":
        return f"上一次回答可能没解释清楚；这次要更直接，不要绕。{thought.content[:80]}"
    if thought.type == "followup":
        return f"有一个待跟进点：{thought.content[:100]}"
    if thought.type == "curiosity":
        return f"有一个轻量好奇点：{thought.content[:100]}"
    return thought.content[:120]


def _row_to_thought(row: sqlite3.Row) -> Thought:
    return Thought(
        id=row["id"],
        scope_id=row["scope_id"],
        user_id=row["user_id"],
        type=row["type"],
        content=row["content"],
        priority=float(row["priority"]),
        status=row["status"],
        created_at=row["created_at"],
        due_at=row["due_at"],
        source_observation_id=row["source_observation_id"],
    )
