from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import AuditLog, MemoryRecord
from .service import MemorySelector


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS p1_social_memory_records (
    memory_id TEXT PRIMARY KEY,
    identity_id TEXT NOT NULL,
    scope_id TEXT,
    predicate TEXT,
    value_text TEXT,
    evidence_text TEXT,
    source_type TEXT,
    source_identity_id TEXT,
    confidence REAL DEFAULT 0.5,
    priority REAL DEFAULT 0.5,
    tags_json TEXT DEFAULT '[]',
    valid_from TEXT,
    valid_to TEXT,
    is_active INTEGER DEFAULT 1,
    render_policy TEXT DEFAULT 'public_summary',
    created_at TEXT,
    updated_at TEXT,
    deleted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_p1_memory_identity_active
ON p1_social_memory_records(identity_id, is_active);

CREATE TABLE IF NOT EXISTS p1_social_memory_audit (
    audit_id TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    actor_internal_id TEXT,
    actor_role TEXT,
    before_json TEXT DEFAULT '{}',
    after_json TEXT DEFAULT '{}',
    reason TEXT,
    correlation_id TEXT,
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_p1_memory_audit_target
ON p1_social_memory_audit(target_id, created_at);
"""


class SQLiteSocialMemoryRepository:
    """SQLite repository for P1 shadow tests.

    It is intentionally not wired into production paths yet. Legacy rows can be
    shadow-read and mapped to `MemoryRecord` without mutating old tables.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def retrieve(self, selector: MemorySelector) -> list[MemoryRecord]:
        self.initialize()
        sql = "SELECT * FROM p1_social_memory_records WHERE 1=1"
        args: list[Any] = []
        if selector.identity_id:
            sql += " AND identity_id=?"
            args.append(selector.identity_id)
        if selector.scope_id:
            sql += " AND scope_id=?"
            args.append(selector.scope_id)
        if selector.memory_id:
            sql += " AND memory_id=?"
            args.append(selector.memory_id)
        if selector.active:
            sql += " AND COALESCE(is_active, 1)=1"
        if selector.predicates:
            sql += f" AND predicate IN ({','.join('?' for _ in selector.predicates)})"
            args.extend(selector.predicates)
        sql += " ORDER BY priority DESC, confidence DESC, updated_at DESC"
        with self.connect() as conn:
            rows = [dict(row) for row in conn.execute(sql, args).fetchall()]
        records = [memory_record_from_row(row) for row in rows]
        if selector.tags:
            wanted = set(selector.tags)
            records = [record for record in records if wanted.intersection(record.tags)]
        if selector.value_contains:
            needle = selector.value_contains.casefold()
            records = [record for record in records if needle in record.value_text.casefold()]
        return records

    def shadow_read_legacy(self) -> list[MemoryRecord]:
        with self.connect() as conn:
            if not _table_exists(conn, "social_memories"):
                return []
            rows = [dict(row) for row in conn.execute("SELECT * FROM social_memories ORDER BY updated_at DESC").fetchall()]
        return [memory_record_from_legacy_row(row) for row in rows]

    def get_audit_trail(self, target_id: str) -> list[AuditLog]:
        self.initialize()
        with self.connect() as conn:
            rows = [dict(row) for row in conn.execute("SELECT * FROM p1_social_memory_audit WHERE target_id=? ORDER BY created_at", (target_id,)).fetchall()]
        return [AuditLog(**row) for row in rows]


def memory_record_from_row(row: dict[str, Any]) -> MemoryRecord:
    return MemoryRecord(
        memory_id=str(row.get("memory_id") or row.get("id") or ""),
        identity_id=str(row.get("identity_id") or row.get("subject_user_id") or ""),
        scope_id=str(row.get("scope_id") or ""),
        predicate=str(row.get("predicate") or "profile"),
        value_text=str(row.get("value_text") or row.get("memory_text") or ""),
        evidence_text=str(row.get("evidence_text") or row.get("raw_evidence") or ""),
        source_type=str(row.get("source_type") or ""),
        source_identity_id=str(row.get("source_identity_id") or row.get("source_user_id") or "") or None,
        confidence=float(row.get("confidence") or 0.0),
        priority=float(row.get("priority") or 0.0),
        tags=tuple(_loads(row.get("tags_json"))),
        valid_from=row.get("valid_from"),
        valid_to=row.get("valid_to"),
        is_active=bool(int(row.get("is_active") if row.get("is_active") is not None else 1)),
        render_policy=str(row.get("render_policy") or "public_summary"),
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
        deleted_at=row.get("deleted_at"),
    )


def memory_record_from_legacy_row(row: dict[str, Any]) -> MemoryRecord:
    tags = _loads(row.get("tags_json"))
    predicate = str(row.get("predicate") or "")
    if not predicate:
        tagset = {str(tag).casefold() for tag in tags}
        if "alias" in tagset:
            predicate = "alias"
        elif "skill" in tagset:
            predicate = "skill"
        elif "preference" in tagset:
            predicate = "preference"
        else:
            predicate = "profile"
    return MemoryRecord(
        memory_id=str(row.get("id") or row.get("memory_id") or ""),
        identity_id=str(row.get("subject_user_id") or row.get("identity_id") or ""),
        scope_id=str(row.get("scope_id") or ""),
        predicate=predicate,
        value_text=str(row.get("value_text") or row.get("memory_text") or ""),
        evidence_text=str(row.get("raw_evidence") or row.get("evidence_text") or ""),
        source_type=str(row.get("source_type") or ""),
        source_identity_id=str(row.get("source_user_id") or row.get("source_identity_id") or "") or None,
        confidence=float(row.get("confidence") or 0.0),
        priority=float(row.get("priority") or 0.0),
        tags=tuple(str(tag) for tag in tags),
        valid_from=None,
        valid_to=None,
        is_active=bool(int(row.get("is_active") if row.get("is_active") is not None else 1)),
        render_policy="public_summary",
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
        deleted_at=row.get("deleted_at"),
    )


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def _loads(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    try:
        data = json.loads(str(value or "[]"))
        return [str(v) for v in data] if isinstance(data, list) else []
    except Exception:
        return []
