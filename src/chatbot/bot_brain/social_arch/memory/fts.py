from __future__ import annotations

import sqlite3

from .models import MemoryRecord
from .service import MemorySelector


def fts5_available(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE temp._p1_fts_probe USING fts5(value)")
        conn.execute("DROP TABLE temp._p1_fts_probe")
        return True
    except sqlite3.Error:
        return False


def search_memory_candidates(
    records: list[MemoryRecord],
    query: str,
    *,
    selector: MemorySelector | None = None,
    force_fallback: bool = False,
) -> list[MemoryRecord]:
    """Return memory candidates for delete/search preview.

    FTS is only a content filter after identity/scope selection. It never
    resolves identity.
    """

    selector = selector or MemorySelector(active=True)
    scoped = _apply_selector(records, selector)
    text = str(query or "").strip()
    if not text:
        return scoped
    if force_fallback:
        return _contains(scoped, text)
    try:
        with sqlite3.connect(":memory:") as conn:
            if not fts5_available(conn):
                return _contains(scoped, text)
            conn.execute("CREATE VIRTUAL TABLE memory_fts USING fts5(memory_id UNINDEXED, value_text, evidence_text)")
            for record in scoped:
                conn.execute(
                    "INSERT INTO memory_fts(memory_id, value_text, evidence_text) VALUES (?, ?, ?)",
                    (record.memory_id, record.value_text, record.evidence_text),
                )
            rows = conn.execute("SELECT memory_id FROM memory_fts WHERE memory_fts MATCH ?", (_fts_query(text),)).fetchall()
            ids = {str(row[0]) for row in rows}
            return [record for record in scoped if record.memory_id in ids]
    except sqlite3.Error:
        return _contains(scoped, text)


def _apply_selector(records: list[MemoryRecord], selector: MemorySelector) -> list[MemoryRecord]:
    out = records
    if selector.identity_id:
        out = [record for record in out if record.identity_id == selector.identity_id]
    if selector.scope_id:
        out = [record for record in out if record.scope_id == selector.scope_id]
    if selector.active:
        out = [record for record in out if record.is_active]
    if selector.predicates:
        wanted = set(selector.predicates)
        out = [record for record in out if record.predicate in wanted]
    if selector.tags:
        wanted_tags = set(selector.tags)
        out = [record for record in out if wanted_tags.intersection(record.tags)]
    return out


def _contains(records: list[MemoryRecord], query: str) -> list[MemoryRecord]:
    needle = query.casefold()
    return [record for record in records if needle in record.value_text.casefold() or needle in record.evidence_text.casefold()]


def _fts_query(query: str) -> str:
    parts = [part.replace('"', '""') for part in str(query).split() if part.strip()]
    if not parts:
        return '""'
    return " OR ".join(f'"{part}"' for part in parts)
