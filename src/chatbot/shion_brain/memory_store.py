from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import math
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, TypeVar

from src.chatbot.settings import get_settings
from src.chatbot.shion_brain.models import (
    AgendaItem,
    BeliefHypothesis,
    DistilledMemory,
    Memory,
    Observation,
    ProceduralPrompt,
    SemanticEdge,
    new_id,
    utc_now,
    utc_now_iso,
)

logger = logging.getLogger(__name__)
T = TypeVar("T")


COGNITIVE_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS shion_semantic_graph (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    relation TEXT NOT NULL,
    object_value TEXT NOT NULL,
    object_type TEXT NOT NULL DEFAULT 'attribute',
    confidence REAL NOT NULL DEFAULT 0.5,
    evidence_refs TEXT NOT NULL DEFAULT '[]',
    tags TEXT NOT NULL DEFAULT '[]',
    conflict_group TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT,
    last_accessed_at TEXT,
    memory_strength REAL NOT NULL DEFAULT 0.5,
    is_permanent INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_shion_semantic_scope ON shion_semantic_graph(scope, scope_id);
CREATE INDEX IF NOT EXISTS idx_shion_semantic_subject_relation ON shion_semantic_graph(subject, relation);
CREATE INDEX IF NOT EXISTS idx_shion_semantic_active_conf ON shion_semantic_graph(is_active, confidence);

CREATE TABLE IF NOT EXISTS shion_procedural_prompts (
    id TEXT PRIMARY KEY,
    scope_id TEXT NOT NULL,
    user_id TEXT,
    context_signature TEXT NOT NULL,
    style_hint TEXT NOT NULL,
    prompt_delta TEXT NOT NULL,
    success_score REAL NOT NULL DEFAULT 0,
    failure_score REAL NOT NULL DEFAULT 0,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    last_outcome TEXT NOT NULL DEFAULT 'neutral',
    tags TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(scope_id, user_id, context_signature, style_hint)
);

CREATE INDEX IF NOT EXISTS idx_shion_proc_scope_user ON shion_procedural_prompts(scope_id, user_id);
CREATE INDEX IF NOT EXISTS idx_shion_proc_effect ON shion_procedural_prompts(success_score, failure_score);

CREATE TABLE IF NOT EXISTS shion_belief_state (
    id TEXT PRIMARY KEY,
    scope_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    hypothesis TEXT NOT NULL,
    probability REAL NOT NULL DEFAULT 0.5,
    evidence_refs TEXT NOT NULL DEFAULT '[]',
    uncertainty_note TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    memory_strength REAL NOT NULL DEFAULT 0.5,
    UNIQUE(scope_id, subject, hypothesis)
);

CREATE INDEX IF NOT EXISTS idx_shion_belief_scope ON shion_belief_state(scope_id, subject);

CREATE TABLE IF NOT EXISTS shion_distillation_runs (
    id TEXT PRIMARY KEY,
    scope_id TEXT NOT NULL,
    reflection_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    surprise_score REAL NOT NULL DEFAULT 0,
    stale_memory_ids TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_shion_distill_scope_time ON shion_distillation_runs(scope_id, created_at);

CREATE TABLE IF NOT EXISTS shion_memory_conflicts (
    id TEXT PRIMARY KEY,
    scope_id TEXT NOT NULL,
    conflict_group TEXT NOT NULL,
    winning_memory_id TEXT,
    losing_memory_ids TEXT NOT NULL DEFAULT '[]',
    resolution_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS shion_memory_archive (
    id TEXT PRIMARY KEY,
    source_table TEXT NOT NULL,
    source_id TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    archive_reason TEXT NOT NULL,
    archived_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_shion_archive_scope_time
ON shion_memory_archive(scope_id, archived_at);

CREATE TABLE IF NOT EXISTS shion_agenda_tree (
    id TEXT PRIMARY KEY,
    scope_id TEXT NOT NULL,
    target_user_id TEXT,
    goal_type TEXT NOT NULL,
    description TEXT NOT NULL,
    priority REAL NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'active',
    metrics_trigger TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_shion_agenda_scope_status_priority
ON shion_agenda_tree(scope_id, status, priority, updated_at);
"""


class SQLiteMemoryStore:
    def __init__(self, path: str | Path | None = None) -> None:
        settings = get_settings()
        self.path = Path(path or Path(settings.data_dir) / "shion_brain" / "shion.db").expanduser()
        self._db_lock = threading.RLock()

    async def initialize(self) -> None:
        await self._run_db(self._initialize_sync)

    async def init_cognitive_schema(self) -> None:
        await self._run_db(self._init_cognitive_schema_sync)

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
        await self._run_db(self._add_memory_sync, memory)

    async def search(self, scope_id: str, query: str, *, limit: int = 8) -> list[Memory]:
        return await self._run_db(self._search_sync, scope_id, query, limit)

    async def recent(self, scope_id: str, *, limit: int = 20) -> list[Memory]:
        return await self._run_db(self._recent_sync, scope_id, limit)

    async def trim_short_term(self, scope_id: str, max_items: int) -> None:
        await self._run_db(self._trim_short_term_sync, scope_id, max_items)

    async def _run_db(self, func: Callable[..., T], *args, retries: int = 3, **kwargs) -> T:
        delay = 0.1
        last_error: sqlite3.OperationalError | None = None
        for attempt in range(retries):
            try:
                return await asyncio.to_thread(func, *args, **kwargs)
            except sqlite3.OperationalError as exc:
                last_error = exc
                if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                    raise
                logger.warning(
                    "SQLite busy while running %s; retry %s/%s",
                    getattr(func, "__name__", repr(func)),
                    attempt + 1,
                    retries,
                )
                await asyncio.sleep(delay)
                delay *= 2
        assert last_error is not None
        raise last_error

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def _initialize_sync(self) -> None:
        with self._db_lock:
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
                conn.executescript(COGNITIVE_DDL)
                self._migrate_cognitive_schema_sync(conn)

    def _init_cognitive_schema_sync(self) -> None:
        with self._db_lock:
            with self._connect() as conn:
                conn.executescript(COGNITIVE_DDL)
                self._migrate_cognitive_schema_sync(conn)

    def _migrate_cognitive_schema_sync(self, conn: sqlite3.Connection) -> None:
        semantic_columns = {row["name"] for row in conn.execute("PRAGMA table_info(shion_semantic_graph)").fetchall()}
        for column, ddl in {
            "last_accessed_at": "ALTER TABLE shion_semantic_graph ADD COLUMN last_accessed_at TEXT",
            "memory_strength": "ALTER TABLE shion_semantic_graph ADD COLUMN memory_strength REAL NOT NULL DEFAULT 0.5",
            "is_permanent": "ALTER TABLE shion_semantic_graph ADD COLUMN is_permanent INTEGER NOT NULL DEFAULT 0",
        }.items():
            if column not in semantic_columns:
                conn.execute(ddl)
        belief_columns = {row["name"] for row in conn.execute("PRAGMA table_info(shion_belief_state)").fetchall()}
        for column, ddl in {
            "is_active": "ALTER TABLE shion_belief_state ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1",
            "memory_strength": "ALTER TABLE shion_belief_state ADD COLUMN memory_strength REAL NOT NULL DEFAULT 0.5",
        }.items():
            if column not in belief_columns:
                conn.execute(ddl)

    def _add_memory_sync(self, memory: Memory) -> None:
        with self._db_lock:
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
        with self._db_lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM memories WHERE scope_id = ? ORDER BY created_at DESC LIMIT ?",
                    (scope_id, limit),
                ).fetchall()
        return [_row_to_memory(row) for row in rows]

    def _trim_short_term_sync(self, scope_id: str, max_items: int) -> None:
        with self._db_lock:
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
        with self._db_lock:
            with self._connect() as conn:
                conn.executemany(
                    "UPDATE memories SET last_accessed_at = ?, access_count = access_count + 1 WHERE id = ?",
                    [(utc_now(), memory_id) for memory_id in ids],
                )

    async def upsert_semantic_edge(self, edge: SemanticEdge) -> str | None:
        return await self._run_db(self._upsert_semantic_edge_sync, edge)

    def _upsert_semantic_edge_sync(self, edge: SemanticEdge) -> str | None:
        edge.clamp()
        now = utc_now_iso()
        try:
            with self._db_lock:
                with self._connect() as conn:
                    active = 1 if edge.is_active else 0
                    winning_id, losing_ids, resolution_note = self._resolve_semantic_conflicts_sync(conn, edge, now)
                    if winning_id and winning_id != edge.id:
                        active = 0
                        resolution_note = resolution_note or "Existing semantic edge kept because its weighted strength is higher."
                    conn.execute(
                        """
                        INSERT INTO shion_semantic_graph
                        (id, scope, scope_id, subject, relation, object_value, object_type,
                         confidence, evidence_refs, tags, conflict_group, is_active,
                         created_at, updated_at, expires_at, last_accessed_at, memory_strength)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            object_value=excluded.object_value,
                            object_type=excluded.object_type,
                            confidence=excluded.confidence,
                            evidence_refs=excluded.evidence_refs,
                            tags=excluded.tags,
                            conflict_group=excluded.conflict_group,
                            is_active=excluded.is_active,
                            updated_at=excluded.updated_at,
                            expires_at=excluded.expires_at,
                            last_accessed_at=COALESCE(shion_semantic_graph.last_accessed_at, excluded.last_accessed_at),
                            memory_strength=MAX(shion_semantic_graph.memory_strength, excluded.memory_strength)
                        """,
                        (
                            edge.id,
                            edge.scope,
                            edge.scope_id,
                            edge.subject,
                            edge.relation,
                            edge.object_value,
                            edge.object_type,
                            edge.confidence,
                            json.dumps(edge.evidence_refs, ensure_ascii=False),
                            json.dumps(edge.tags, ensure_ascii=False),
                            edge.conflict_group,
                            active,
                            edge.created_at,
                            now,
                            edge.expires_at,
                            now,
                            max(edge.confidence, 0.5),
                        ),
                    )
                    if losing_ids:
                        conn.executemany(
                            """
                            UPDATE shion_semantic_graph
                            SET is_active = 0, updated_at = ?
                            WHERE id = ?
                            """,
                            [(now, memory_id) for memory_id in losing_ids if memory_id != edge.id],
                        )
                    if winning_id:
                        conn.execute(
                            """
                            UPDATE shion_semantic_graph
                            SET memory_strength = MIN(1.0, COALESCE(memory_strength, confidence) + 0.15),
                                is_active = 1,
                                updated_at = ?
                            WHERE id = ?
                            """,
                            (now, winning_id),
                        )
                        conflict_losers = losing_ids if winning_id == edge.id else [edge.id]
                        if conflict_losers:
                            self._write_conflict_sync(
                                conn,
                                scope_id=edge.scope_id,
                                conflict_group=edge.conflict_group or f"semantic:{edge.subject}:{edge.relation}",
                                winning_id=winning_id,
                                losing_ids=conflict_losers,
                                note=resolution_note or "Semantic conflict resolved by confidence, memory strength, and recency.",
                                now=now,
                            )
                    logger.debug("Semantic edge upserted: id=%s active=%s winning=%s", edge.id, active, winning_id)
                    return edge.id
        except sqlite3.OperationalError:
            raise
        except Exception:
            logger.exception("Failed to upsert semantic edge")
            return None

    def _resolve_semantic_conflicts_sync(
        self,
        conn: sqlite3.Connection,
        edge: SemanticEdge,
        now: str,
    ) -> tuple[str | None, list[str], str]:
        clauses = ["(scope_id = ? AND subject = ? AND relation = ? AND object_value <> ? AND is_active = 1)"]
        params: list[Any] = [edge.scope_id, edge.subject, edge.relation, edge.object_value]
        if edge.conflict_group:
            clauses.append("(scope_id = ? AND conflict_group = ? AND id <> ? AND is_active = 1)")
            params.extend([edge.scope_id, edge.conflict_group, edge.id])
        rows = conn.execute(
            f"SELECT * FROM shion_semantic_graph WHERE {' OR '.join(clauses)}",
            params,
        ).fetchall()
        if not rows:
            return None, [], ""
        new_score = _semantic_conflict_score(edge.confidence, max(edge.confidence, 0.5), now)
        best_id = edge.id
        best_score = new_score
        losing_ids: list[str] = []
        for row in rows:
            old_score = _semantic_conflict_score(
                float(row["confidence"]),
                float(row["memory_strength"] if row["memory_strength"] is not None else row["confidence"]),
                row["updated_at"],
            )
            if old_score > best_score:
                if best_id == edge.id:
                    losing_ids = []
                best_id = row["id"]
                best_score = old_score
            else:
                losing_ids.append(row["id"])
        if best_id == edge.id:
            losing_ids = [row["id"] for row in rows if row["id"] != edge.id]
            note = "New semantic evidence supersedes historical memory."
        else:
            note = "Historical semantic memory retained over lower-scored new evidence."
        logger.info(
            "Semantic conflict resolved scope=%s subject=%s relation=%s winner=%s losers=%s",
            edge.scope_id,
            edge.subject,
            edge.relation,
            best_id,
            losing_ids if best_id == edge.id else [edge.id],
        )
        return best_id, losing_ids, note

    def _write_conflict_sync(
        self,
        conn: sqlite3.Connection,
        *,
        scope_id: str,
        conflict_group: str,
        winning_id: str,
        losing_ids: list[str],
        note: str,
        now: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO shion_memory_conflicts
            (id, scope_id, conflict_group, winning_memory_id, losing_memory_ids, resolution_note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("conflict"),
                scope_id,
                conflict_group,
                winning_id,
                json.dumps(losing_ids, ensure_ascii=False),
                note,
                now,
            ),
        )

    async def search_semantic_edges(
        self,
        scope_id: str,
        *,
        subject: str | None = None,
        relation: str | None = None,
        tags: Iterable[str] | None = None,
        min_confidence: float = 0.35,
        limit: int = 12,
    ) -> list[SemanticEdge]:
        return await self._run_db(self._search_semantic_edges_sync, scope_id, subject, relation, list(tags or []), min_confidence, limit)

    def _search_semantic_edges_sync(
        self,
        scope_id: str,
        subject: str | None,
        relation: str | None,
        tags: list[str],
        min_confidence: float,
        limit: int,
    ) -> list[SemanticEdge]:
        try:
            sql = "SELECT * FROM shion_semantic_graph WHERE scope_id = ? AND is_active = 1 AND confidence >= ?"
            params: list[Any] = [scope_id, min_confidence]
            if subject:
                sql += " AND subject = ?"
                params.append(subject)
            if relation:
                sql += " AND relation = ?"
                params.append(relation)
            sql += " ORDER BY confidence DESC, updated_at DESC LIMIT ?"
            params.append(limit * 3)
            with self._db_lock:
                with self._connect() as conn:
                    rows = conn.execute(sql, params).fetchall()
            results = []
            for row in rows:
                row_tags = json.loads(row["tags"] or "[]")
                if tags and not any(tag in row_tags for tag in tags):
                    continue
                results.append(_row_to_semantic_edge(row, row_tags))
                if len(results) >= limit:
                    break
            if results:
                self._boost_semantic_edges_sync([edge.id for edge in results], amount=0.2)
            return results
        except sqlite3.OperationalError:
            raise
        except Exception:
            logger.exception("Failed to search semantic edges")
            return []

    def _boost_semantic_edges_sync(self, edge_ids: list[str], *, amount: float) -> None:
        if not edge_ids:
            return
        now = utc_now_iso()
        with self._db_lock:
            with self._connect() as conn:
                conn.executemany(
                    """
                    UPDATE shion_semantic_graph
                    SET last_accessed_at = ?,
                        memory_strength = MIN(1.0, COALESCE(memory_strength, confidence) + ?)
                    WHERE id = ?
                    """,
                    [(now, amount, edge_id) for edge_id in edge_ids],
                )

    async def record_procedural_outcome(
        self,
        *,
        scope_id: str,
        user_id: str | None,
        context_signature: str,
        style_hint: str,
        prompt_delta: str,
        outcome: str,
        tags: list[str] | None = None,
        weight: float = 1.0,
    ) -> None:
        await self._run_db(
            self._record_procedural_outcome_sync,
            scope_id,
            user_id,
            context_signature,
            style_hint,
            prompt_delta,
            outcome,
            tags or [],
            weight,
        )

    def _record_procedural_outcome_sync(
        self,
        scope_id: str,
        user_id: str | None,
        context_signature: str,
        style_hint: str,
        prompt_delta: str,
        outcome: str,
        tags: list[str],
        weight: float,
    ) -> None:
        now = utc_now_iso()
        success_delta = weight if outcome == "success" else 0.0
        failure_delta = weight if outcome == "failure" else 0.0
        try:
            with self._db_lock:
                with self._connect() as conn:
                    existing = conn.execute(
                        """
                        SELECT id FROM shion_procedural_prompts
                        WHERE scope_id = ? AND context_signature = ? AND style_hint = ?
                          AND ((user_id IS NULL AND ? IS NULL) OR user_id = ?)
                        """,
                        (scope_id, context_signature, style_hint, user_id, user_id),
                    ).fetchone()
                    if existing:
                        conn.execute(
                            """
                            UPDATE shion_procedural_prompts
                            SET prompt_delta = ?,
                                success_score = success_score + ?,
                                failure_score = failure_score + ?,
                                evidence_count = evidence_count + 1,
                                last_outcome = ?,
                                tags = ?,
                                updated_at = ?
                            WHERE id = ?
                            """,
                            (prompt_delta, success_delta, failure_delta, outcome, json.dumps(tags, ensure_ascii=False), now, existing["id"]),
                        )
                    else:
                        conn.execute(
                            """
                            INSERT INTO shion_procedural_prompts
                            (id, scope_id, user_id, context_signature, style_hint, prompt_delta,
                             success_score, failure_score, evidence_count, last_outcome, tags, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                            """,
                            (
                                new_id("proc"),
                                scope_id,
                                user_id,
                                context_signature,
                                style_hint,
                                prompt_delta,
                                success_delta,
                                failure_delta,
                                outcome,
                                json.dumps(tags, ensure_ascii=False),
                                now,
                                now,
                            ),
                        )
        except sqlite3.OperationalError:
            raise
        except Exception:
            logger.exception("Failed to record procedural outcome")

    async def retrieve_procedural_prompts(
        self,
        *,
        scope_id: str,
        user_id: str | None,
        context_signature: str | None = None,
        limit: int = 5,
    ) -> list[ProceduralPrompt]:
        return await self._run_db(self._retrieve_procedural_prompts_sync, scope_id, user_id, context_signature, limit)

    def _retrieve_procedural_prompts_sync(self, scope_id: str, user_id: str | None, context_signature: str | None, limit: int) -> list[ProceduralPrompt]:
        try:
            sql = """
            SELECT * FROM shion_procedural_prompts
            WHERE scope_id = ? AND (user_id IS NULL OR user_id = ?)
            """
            params: list[Any] = [scope_id, user_id]
            if context_signature:
                sql += " AND context_signature = ?"
                params.append(context_signature)
            sql += " ORDER BY (success_score / (success_score + failure_score + 0.000001)) DESC, evidence_count DESC, updated_at DESC LIMIT ?"
            params.append(limit)
            with self._db_lock:
                with self._connect() as conn:
                    rows = conn.execute(sql, params).fetchall()
            return [_row_to_procedural_prompt(row) for row in rows]
        except sqlite3.OperationalError:
            raise
        except Exception:
            logger.exception("Failed to retrieve procedural prompts")
            return []

    async def upsert_belief(self, belief: BeliefHypothesis) -> None:
        await self._run_db(self._upsert_belief_sync, belief)

    def _upsert_belief_sync(self, belief: BeliefHypothesis) -> None:
        belief.clamp()
        now = utc_now_iso()
        try:
            with self._db_lock:
                with self._connect() as conn:
                    winning_id, losing_ids, new_active, new_probability, note = self._resolve_belief_conflicts_sync(conn, belief, now)
                    conn.execute(
                        """
                        INSERT INTO shion_belief_state
                        (id, scope_id, subject, hypothesis, probability, evidence_refs, uncertainty_note, updated_at, is_active, memory_strength)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(scope_id, subject, hypothesis)
                        DO UPDATE SET
                            probability=excluded.probability,
                            evidence_refs=excluded.evidence_refs,
                            uncertainty_note=excluded.uncertainty_note,
                            updated_at=excluded.updated_at,
                            is_active=excluded.is_active,
                            memory_strength=MAX(shion_belief_state.memory_strength, excluded.memory_strength)
                        """,
                        (
                            belief.id,
                            belief.scope_id,
                            belief.subject,
                            belief.hypothesis,
                            new_probability,
                            json.dumps(belief.evidence_refs, ensure_ascii=False),
                            belief.uncertainty_note,
                            now,
                            1 if new_active else 0,
                            max(new_probability, 0.35),
                        ),
                    )
                    if losing_ids:
                        conn.executemany(
                            """
                            UPDATE shion_belief_state
                            SET is_active = 0,
                                probability = MAX(0.05, probability * 0.35),
                                updated_at = ?
                            WHERE id = ?
                            """,
                            [(now, belief_id) for belief_id in losing_ids if belief_id != belief.id],
                        )
                    if winning_id:
                        conn.execute(
                            """
                            UPDATE shion_belief_state
                            SET memory_strength = MIN(1.0, COALESCE(memory_strength, probability) + 0.12),
                                updated_at = ?
                            WHERE id = ?
                            """,
                            (now, winning_id),
                        )
                        conflict_losers = losing_ids if winning_id == belief.id else [belief.id]
                        if conflict_losers:
                            self._write_conflict_sync(
                                conn,
                                scope_id=belief.scope_id,
                                conflict_group=f"belief:{belief.subject}",
                                winning_id=winning_id,
                                losing_ids=conflict_losers,
                                note=note or "Belief conflict resolved by probability, strength, and recency.",
                                now=now,
                            )
                    logger.debug("Belief upserted: id=%s active=%s winning=%s", belief.id, new_active, winning_id)
        except sqlite3.OperationalError:
            raise
        except Exception:
            logger.exception("Failed to upsert belief hypothesis")

    def _resolve_belief_conflicts_sync(
        self,
        conn: sqlite3.Connection,
        belief: BeliefHypothesis,
        now: str,
    ) -> tuple[str | None, list[str], bool, float, str]:
        rows = conn.execute(
            """
            SELECT * FROM shion_belief_state
            WHERE scope_id = ? AND subject = ? AND hypothesis <> ? AND is_active = 1
            """,
            (belief.scope_id, belief.subject, belief.hypothesis),
        ).fetchall()
        if not rows:
            return None, [], True, belief.probability, ""
        new_score = _semantic_conflict_score(belief.probability, max(belief.probability, 0.35), now)
        best_id = belief.id
        best_score = new_score
        for row in rows:
            old_score = _semantic_conflict_score(
                float(row["probability"]),
                float(row["memory_strength"] if row["memory_strength"] is not None else row["probability"]),
                row["updated_at"],
            )
            if old_score > best_score:
                best_id = row["id"]
                best_score = old_score
        if best_id == belief.id:
            losing_ids = [row["id"] for row in rows]
            note = "New belief hypothesis supersedes older competing hypotheses."
            new_active = True
            new_probability = belief.probability
        else:
            losing_ids = []
            note = "Existing belief retained; new competing hypothesis stored inactive with reduced probability."
            new_active = False
            new_probability = max(0.05, belief.probability * 0.35)
        logger.info(
            "Belief conflict resolved scope=%s subject=%s winner=%s new_active=%s",
            belief.scope_id,
            belief.subject,
            best_id,
            new_active,
        )
        return best_id, losing_ids, new_active, new_probability, note

    async def retrieve_beliefs(
        self,
        *,
        scope_id: str,
        subject: str | None = None,
        min_probability: float = 0.25,
        limit: int = 10,
    ) -> list[BeliefHypothesis]:
        return await self._run_db(self._retrieve_beliefs_sync, scope_id, subject, min_probability, limit)

    def _retrieve_beliefs_sync(self, scope_id: str, subject: str | None, min_probability: float, limit: int) -> list[BeliefHypothesis]:
        try:
            sql = "SELECT * FROM shion_belief_state WHERE scope_id = ? AND probability >= ? AND is_active = 1"
            params: list[Any] = [scope_id, min_probability]
            if subject:
                sql += " AND subject = ?"
                params.append(subject)
            sql += " ORDER BY probability DESC, updated_at DESC LIMIT ?"
            params.append(limit)
            with self._db_lock:
                with self._connect() as conn:
                    rows = conn.execute(sql, params).fetchall()
            return [_row_to_belief(row) for row in rows]
        except sqlite3.OperationalError:
            raise
        except Exception:
            logger.exception("Failed to retrieve belief hypotheses")
            return []

    async def save_distillation_result(self, result: DistilledMemory) -> None:
        await self._run_db(self._save_distillation_run_sync, result)
        for edge in result.semantic_edges:
            await self.upsert_semantic_edge(edge)
        for belief in result.belief_updates:
            await self.upsert_belief(belief)
        for proc in result.procedural_updates:
            await self.record_procedural_outcome(
                scope_id=proc.scope_id,
                user_id=proc.user_id,
                context_signature=proc.context_signature,
                style_hint=proc.style_hint,
                prompt_delta=proc.prompt_delta,
                outcome=proc.last_outcome,
                tags=proc.tags,
                weight=max(1.0, float(proc.evidence_count or 1)),
            )

    def _save_distillation_run_sync(self, result: DistilledMemory) -> None:
        try:
            with self._db_lock:
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO shion_distillation_runs
                        (id, scope_id, reflection_type, summary, surprise_score, stale_memory_ids, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            result.id,
                            result.scope_id,
                            result.reflection_type,
                            result.summary,
                            result.surprise_score,
                            json.dumps(result.stale_memory_ids, ensure_ascii=False),
                            result.created_at,
                        ),
                    )
        except sqlite3.OperationalError:
            raise
        except Exception:
            logger.exception("Failed to save distillation run")

    async def get_active_scopes(self, since_hours: int = 3) -> list[str]:
        return await self._run_db(self._get_active_scopes_sync, since_hours)

    def _get_active_scopes_sync(self, since_hours: int) -> list[str]:
        cutoff = time.time() - since_hours * 3600
        try:
            with self._db_lock:
                with self._connect() as conn:
                    has_thoughts = conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'thoughts'"
                    ).fetchone()
                    if has_thoughts:
                        rows = conn.execute(
                            """
                            SELECT DISTINCT scope_id
                            FROM memories
                            WHERE created_at >= ?
                              AND scope_id NOT IN (
                                  SELECT scope_id FROM thoughts
                                  WHERE status = 'locked'
                              )
                            ORDER BY scope_id
                            """,
                            (_iso_from_epoch(cutoff),),
                        ).fetchall()
                    else:
                        rows = conn.execute(
                            """
                            SELECT DISTINCT scope_id
                            FROM memories
                            WHERE created_at >= ?
                            ORDER BY scope_id
                            """,
                            (_iso_from_epoch(cutoff),),
                        ).fetchall()
            return [str(row["scope_id"]) for row in rows]
        except sqlite3.OperationalError:
            raise
        except Exception:
            logger.exception("Failed to fetch active scopes")
            return []

    async def create_agenda_item(
        self,
        item: AgendaItem,
    ) -> str | None:
        item.clamp()
        return await self._run_db(self._create_agenda_item_sync, item)

    def _create_agenda_item_sync(self, item: AgendaItem) -> str | None:
        try:
            with self._db_lock:
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO shion_agenda_tree
                        (id, scope_id, target_user_id, goal_type, description, priority, status, metrics_trigger, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item.id,
                            item.scope_id,
                            item.target_user_id,
                            item.goal_type,
                            item.description,
                            item.priority,
                            item.status,
                            json.dumps(item.metrics_trigger, ensure_ascii=False),
                            item.created_at,
                            item.updated_at,
                        ),
                    )
                    logger.info("Agenda item persisted: id=%s scope=%s type=%s priority=%.2f", item.id, item.scope_id, item.goal_type, item.priority)
                    return item.id
        except sqlite3.OperationalError:
            raise
        except Exception:
            logger.exception("Failed to create agenda item: scope=%s type=%s", item.scope_id, item.goal_type)
            return None

    async def list_active_agenda_items(self, scope_id: str, *, limit: int = 5) -> list[AgendaItem]:
        return await self._run_db(self._list_active_agenda_items_sync, scope_id, limit)

    def _list_active_agenda_items_sync(self, scope_id: str, limit: int) -> list[AgendaItem]:
        try:
            with self._db_lock:
                with self._connect() as conn:
                    rows = conn.execute(
                        """
                        SELECT * FROM shion_agenda_tree
                        WHERE scope_id = ? AND status = 'active'
                        ORDER BY priority DESC, updated_at ASC
                        LIMIT ?
                        """,
                        (scope_id, limit),
                    ).fetchall()
            return [_row_to_agenda_item(row) for row in rows]
        except sqlite3.OperationalError:
            raise
        except Exception:
            logger.exception("Failed to list active agenda items for scope=%s", scope_id)
            return []

    async def complete_agenda_item(self, agenda_id: str) -> None:
        await self._run_db(self._set_agenda_status_sync, agenda_id, "completed", 0.0)

    async def deprioritize_agenda_item(self, agenda_id: str, *, amount: float = 0.15) -> None:
        await self._run_db(self._deprioritize_agenda_item_sync, agenda_id, amount)

    async def has_active_agenda(self, scope_id: str, *, goal_type: str | None = None) -> bool:
        return await self._run_db(self._has_active_agenda_sync, scope_id, goal_type)

    def _has_active_agenda_sync(self, scope_id: str, goal_type: str | None) -> bool:
        try:
            with self._db_lock:
                with self._connect() as conn:
                    if goal_type:
                        row = conn.execute(
                            "SELECT 1 FROM shion_agenda_tree WHERE scope_id = ? AND goal_type = ? AND status = 'active' LIMIT 1",
                            (scope_id, goal_type),
                        ).fetchone()
                    else:
                        row = conn.execute(
                            "SELECT 1 FROM shion_agenda_tree WHERE scope_id = ? AND status = 'active' LIMIT 1",
                            (scope_id,),
                        ).fetchone()
            return row is not None
        except sqlite3.OperationalError:
            raise
        except Exception:
            logger.exception("Failed to check agenda existence for scope=%s", scope_id)
            return False

    def _set_agenda_status_sync(self, agenda_id: str, status: str, priority: float | None = None) -> None:
        now = utc_now_iso()
        try:
            with self._db_lock:
                with self._connect() as conn:
                    if priority is None:
                        conn.execute(
                            "UPDATE shion_agenda_tree SET status = ?, updated_at = ? WHERE id = ?",
                            (status, now, agenda_id),
                        )
                    else:
                        conn.execute(
                            "UPDATE shion_agenda_tree SET status = ?, priority = ?, updated_at = ? WHERE id = ?",
                            (status, priority, now, agenda_id),
                        )
        except sqlite3.OperationalError:
            raise
        except Exception:
            logger.exception("Failed to set agenda status: id=%s status=%s", agenda_id, status)

    def _deprioritize_agenda_item_sync(self, agenda_id: str, amount: float) -> None:
        now = utc_now_iso()
        try:
            with self._db_lock:
                with self._connect() as conn:
                    row = conn.execute("SELECT priority FROM shion_agenda_tree WHERE id = ?", (agenda_id,)).fetchone()
                    if not row:
                        return
                    new_priority = max(0.0, float(row["priority"]) - amount)
                    status = "abandoned" if new_priority <= 0.05 else "active"
                    conn.execute(
                        "UPDATE shion_agenda_tree SET priority = ?, status = ?, updated_at = ? WHERE id = ?",
                        (new_priority, status, now, agenda_id),
                    )
                    logger.info("Agenda item deprioritized: id=%s priority=%.2f status=%s", agenda_id, new_priority, status)
        except sqlite3.OperationalError:
            raise
        except Exception:
            logger.exception("Failed to deprioritize agenda item: id=%s", agenda_id)

    async def deactivate_stale_semantic_edges(
        self,
        *,
        scope_id: str,
        memory_ids: list[str] | None = None,
        reason: str = "stale_or_redundant",
        threshold: float = 0.1,
        decay_lambda: float = 0.035,
    ) -> int:
        return await self._run_db(
            self._deactivate_stale_semantic_edges_sync,
            scope_id,
            memory_ids or [],
            reason,
            threshold,
            decay_lambda,
        )

    def _deactivate_stale_semantic_edges_sync(
        self,
        scope_id: str,
        memory_ids: list[str],
        reason: str,
        threshold: float,
        decay_lambda: float,
    ) -> int:
        now = utc_now_iso()
        try:
            with self._db_lock:
                with self._connect() as conn:
                    explicit_ids = set(memory_ids)
                    candidates = conn.execute(
                        """
                        SELECT * FROM shion_semantic_graph
                        WHERE scope_id = ? AND is_active = 1 AND is_permanent = 0
                        """,
                        (scope_id,),
                    ).fetchall()
                    stale_ids: list[str] = list(explicit_ids)
                    archive_rows: list[tuple[str, str, str, str, str, str, str]] = []
                    for row in candidates:
                        edge_id = row["id"]
                        if edge_id in explicit_ids:
                            archive_rows.append(_archive_row("shion_semantic_graph", edge_id, scope_id, dict(row), reason, now))
                            continue
                        updated_at = row["last_accessed_at"] or row["updated_at"]
                        hours = _hours_since(updated_at)
                        strength = float(row["memory_strength"] if row["memory_strength"] is not None else row["confidence"])
                        decayed = strength * math.exp(-decay_lambda * hours)
                        if decayed < threshold:
                            stale_ids.append(edge_id)
                            archive_rows.append(_archive_row("shion_semantic_graph", edge_id, scope_id, dict(row), "decayed", now))
                    if archive_rows:
                        conn.executemany(
                            """
                            INSERT OR REPLACE INTO shion_memory_archive
                            (id, source_table, source_id, scope_id, payload, archive_reason, archived_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            archive_rows,
                        )
                    if stale_ids:
                        conn.executemany(
                            "UPDATE shion_semantic_graph SET is_active = 0, updated_at = ? WHERE scope_id = ? AND id = ?",
                            [(now, scope_id, memory_id) for memory_id in stale_ids],
                        )
                    memory_rows = conn.execute(
                        """
                        SELECT * FROM memories
                        WHERE scope_id = ? AND type = 'short_term' AND importance < 0.35
                        """,
                        (scope_id,),
                    ).fetchall()
                    archive_memory: list[tuple[str, str, str, str, str, str, str]] = []
                    delete_memory_ids: list[str] = []
                    for row in memory_rows:
                        hours = _hours_since(row["last_accessed_at"] or row["created_at"])
                        decayed = float(row["importance"]) * math.exp(-decay_lambda * hours)
                        if decayed < threshold:
                            delete_memory_ids.append(row["id"])
                            archive_memory.append(_archive_row("memories", row["id"], scope_id, dict(row), "decayed", now))
                    if archive_memory:
                        conn.executemany(
                            """
                            INSERT OR REPLACE INTO shion_memory_archive
                            (id, source_table, source_id, scope_id, payload, archive_reason, archived_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            archive_memory,
                        )
                    if delete_memory_ids:
                        conn.executemany("DELETE FROM memories WHERE id = ?", [(memory_id,) for memory_id in delete_memory_ids])
                    return len(stale_ids) + len(delete_memory_ids)
        except sqlite3.OperationalError:
            raise
        except Exception:
            logger.exception("Failed to deactivate stale semantic edges: %s", reason)
            return 0


def _semantic_conflict_score(confidence: float, strength: float, updated_at: str) -> float:
    freshness = math.exp(-0.01 * _hours_since(updated_at))
    return confidence * 0.55 + strength * 0.30 + freshness * 0.15


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


def _row_to_semantic_edge(row: sqlite3.Row, row_tags: list[str] | None = None) -> SemanticEdge:
    return SemanticEdge(
        id=row["id"],
        scope=row["scope"],
        scope_id=row["scope_id"],
        subject=row["subject"],
        relation=row["relation"],
        object_value=row["object_value"],
        object_type=row["object_type"],
        confidence=float(row["confidence"]),
        evidence_refs=json.loads(row["evidence_refs"] or "[]"),
        tags=row_tags if row_tags is not None else json.loads(row["tags"] or "[]"),
        conflict_group=row["conflict_group"],
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        expires_at=row["expires_at"],
    )


def _row_to_procedural_prompt(row: sqlite3.Row) -> ProceduralPrompt:
    return ProceduralPrompt(
        id=row["id"],
        scope_id=row["scope_id"],
        user_id=row["user_id"],
        context_signature=row["context_signature"],
        style_hint=row["style_hint"],
        prompt_delta=row["prompt_delta"],
        success_score=float(row["success_score"]),
        failure_score=float(row["failure_score"]),
        evidence_count=int(row["evidence_count"]),
        last_outcome=row["last_outcome"],
        tags=json.loads(row["tags"] or "[]"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_belief(row: sqlite3.Row) -> BeliefHypothesis:
    return BeliefHypothesis(
        id=row["id"],
        scope_id=row["scope_id"],
        subject=row["subject"],
        hypothesis=row["hypothesis"],
        probability=float(row["probability"]),
        evidence_refs=json.loads(row["evidence_refs"] or "[]"),
        uncertainty_note=row["uncertainty_note"] or "",
        updated_at=row["updated_at"],
    )


def _row_to_agenda_item(row: sqlite3.Row) -> AgendaItem:
    return AgendaItem(
        id=row["id"],
        scope_id=row["scope_id"],
        target_user_id=row["target_user_id"],
        goal_type=row["goal_type"],
        description=row["description"],
        priority=float(row["priority"]),
        status=row["status"],
        metrics_trigger=json.loads(row["metrics_trigger"] or "{}"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
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


def _parse_iso(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _hours_since(value: str | None) -> float:
    delta = datetime.now(timezone.utc) - _parse_iso(value)
    return max(0.0, delta.total_seconds() / 3600)


def _iso_from_epoch(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def _archive_row(
    source_table: str,
    source_id: str,
    scope_id: str,
    payload: dict[str, Any],
    reason: str,
    archived_at: str,
) -> tuple[str, str, str, str, str, str, str]:
    return (
        f"archive_{source_table}_{source_id}",
        source_table,
        source_id,
        scope_id,
        json.dumps(payload, ensure_ascii=False, default=str),
        reason,
        archived_at,
    )
