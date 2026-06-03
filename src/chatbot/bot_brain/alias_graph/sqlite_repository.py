from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import AliasNode
from .repository import normalize_alias_value


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS p1_alias_nodes (
    alias_id TEXT PRIMARY KEY,
    identity_id TEXT NOT NULL,
    alias_value TEXT NOT NULL,
    alias_norm TEXT NOT NULL,
    alias_type TEXT NOT NULL,
    scope_id TEXT,
    source_memory_id TEXT,
    confidence REAL DEFAULT 0.5,
    active INTEGER DEFAULT 1,
    created_at TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_p1_alias_norm
ON p1_alias_nodes(alias_norm, scope_id, active);
"""


class SQLiteAliasGraphRepository:
    """SQLite AliasGraph shadow repository.

    This repository supports schema tests and legacy projection reads. It does
    not make arbitrary memory body text identity evidence.
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

    def shadow_read_legacy(self) -> list[AliasNode]:
        with self.connect() as conn:
            nodes: list[AliasNode] = []
            if _table_exists(conn, "social_users"):
                for row in conn.execute("SELECT user_id, display_name, aliases_json, first_seen_at, last_seen_at FROM social_users").fetchall():
                    nodes.extend(_nodes_from_user_row(dict(row)))
            if _table_exists(conn, "social_alias_name_index"):
                for row in conn.execute("SELECT * FROM social_alias_name_index WHERE COALESCE(active, 1)=1").fetchall():
                    nodes.append(alias_node_from_index_row(dict(row)))
        return _dedupe_nodes(nodes)


def alias_node_from_index_row(row: dict[str, Any]) -> AliasNode:
    value = str(row.get("label") or row.get("alias_value") or "")
    return AliasNode(
        alias_id=str(row.get("id") or f"alias_{row.get('user_id')}_{normalize_alias_value(value)}"),
        identity_id=str(row.get("user_id") or row.get("identity_id") or ""),
        alias_value=value,
        alias_norm=str(row.get("label_key") or normalize_alias_value(value)),
        alias_type=str(row.get("label_type") or "alias"),
        scope_id=str(row.get("group_id") or row.get("scope_id") or ""),
        source_memory_id=str(row.get("memory_id") or "") or None,
        confidence=float(row.get("confidence") or 0.5),
        active=bool(int(row.get("active") if row.get("active") is not None else 1)),
        created_at=str(row.get("updated_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
    )


def _nodes_from_user_row(row: dict[str, Any]) -> list[AliasNode]:
    uid = str(row.get("user_id") or "")
    labels: list[tuple[str, str, float]] = []
    display = str(row.get("display_name") or "").strip()
    if display:
        labels.append((display, "display_name", 1.0))
    try:
        aliases = json.loads(str(row.get("aliases_json") or "[]"))
        if isinstance(aliases, list):
            labels.extend((str(alias), "alias", 0.9) for alias in aliases if str(alias).strip())
    except Exception:
        pass
    nodes: list[AliasNode] = []
    for value, alias_type, confidence in labels:
        nodes.append(
            AliasNode(
                alias_id=f"legacy_user_{uid}_{alias_type}_{normalize_alias_value(value)}",
                identity_id=uid,
                alias_value=value,
                alias_norm=normalize_alias_value(value),
                alias_type=alias_type,
                scope_id="",
                source_memory_id=None,
                confidence=confidence,
                active=True,
                created_at=str(row.get("first_seen_at") or ""),
                updated_at=str(row.get("last_seen_at") or ""),
            )
        )
    return nodes


def _dedupe_nodes(nodes: list[AliasNode]) -> list[AliasNode]:
    out: list[AliasNode] = []
    seen: set[tuple[str, str, str]] = set()
    for node in nodes:
        key = (node.identity_id, node.alias_norm, node.scope_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(node)
    return out


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None
