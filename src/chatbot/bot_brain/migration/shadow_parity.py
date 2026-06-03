from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.chatbot.bot_brain.alias_graph.models import AliasNode
from src.chatbot.bot_brain.alias_graph.sqlite_repository import SQLiteAliasGraphRepository
from src.chatbot.bot_brain.social_arch.memory.models import MemoryRecord
from src.chatbot.bot_brain.social_arch.memory.sqlite_repository import SQLiteSocialMemoryRepository


Severity = Literal["info", "warning", "error"]

OWNER_POLLUTION_RE = re.compile(r"(主人|owner|owner|管理员|owner|master)", re.I)
INTERNAL_ID_RE = re.compile(r"\b\d{5,12}\b")


@dataclass(frozen=True)
class ShadowParityIssue:
    kind: str
    legacy_id: str
    shadow_id: str | None
    severity: Severity
    message: str


@dataclass(frozen=True)
class ShadowParityReport:
    legacy_memory_count: int
    shadow_memory_count: int
    legacy_alias_count: int
    shadow_alias_count: int
    active_memory_mismatches: int
    deleted_memory_mismatches: int
    alias_mismatches: int
    owner_pollution_candidates: int
    issues: tuple[ShadowParityIssue, ...]

    def public_summary(self) -> str:
        return (
            "shadow parity: "
            f"memories {self.shadow_memory_count}/{self.legacy_memory_count}, "
            f"aliases {self.shadow_alias_count}/{self.legacy_alias_count}, "
            f"issues {len(self.issues)}"
        )


class ShadowParityChecker:
    """Compare legacy social memory rows with P1 shadow projections.

    This is instrumentation only. It reads legacy SQLite rows and P1 shadow
    projections; it never writes migration rows, enables dual-write, or changes
    runtime cutover state.
    """

    def __init__(self, legacy_db_path: str | Path) -> None:
        self.legacy_db_path = Path(legacy_db_path)

    def build_report(
        self,
        *,
        shadow_memories: tuple[MemoryRecord, ...] | None = None,
        shadow_aliases: tuple[AliasNode, ...] | None = None,
    ) -> ShadowParityReport:
        legacy_memory_rows = _legacy_memory_rows(self.legacy_db_path)
        legacy_alias_rows = _legacy_alias_rows(self.legacy_db_path)
        shadow_memory_list = list(shadow_memories) if shadow_memories is not None else SQLiteSocialMemoryRepository(self.legacy_db_path).shadow_read_legacy()
        shadow_alias_list = list(shadow_aliases) if shadow_aliases is not None else SQLiteAliasGraphRepository(self.legacy_db_path).shadow_read_legacy()

        issues: list[ShadowParityIssue] = []
        active_mismatches = _count_active_mismatches(legacy_memory_rows, shadow_memory_list, issues)
        deleted_mismatches = _count_deleted_mismatches(legacy_memory_rows, shadow_memory_list, issues)
        alias_mismatches = _count_alias_mismatches(legacy_alias_rows, shadow_alias_list, issues)
        owner_candidates = _count_owner_pollution_candidates(shadow_memory_list, issues)

        return ShadowParityReport(
            legacy_memory_count=len(legacy_memory_rows),
            shadow_memory_count=len(shadow_memory_list),
            legacy_alias_count=len(legacy_alias_rows),
            shadow_alias_count=len(shadow_alias_list),
            active_memory_mismatches=active_mismatches,
            deleted_memory_mismatches=deleted_mismatches,
            alias_mismatches=alias_mismatches,
            owner_pollution_candidates=owner_candidates,
            issues=tuple(issues),
        )


def render_public_parity_summary(report: ShadowParityReport) -> str:
    return INTERNAL_ID_RE.sub("[internal]", report.public_summary())


def _legacy_memory_rows(path: Path) -> list[dict]:
    with _connect(path) as conn:
        if not _table_exists(conn, "social_memories"):
            return []
        return [dict(row) for row in conn.execute("SELECT * FROM social_memories ORDER BY id").fetchall()]


def _legacy_alias_rows(path: Path) -> list[dict]:
    with _connect(path) as conn:
        rows: list[dict] = []
        if _table_exists(conn, "social_users"):
            for row in conn.execute("SELECT user_id, display_name, aliases_json FROM social_users").fetchall():
                data = dict(row)
                if str(data.get("display_name") or "").strip():
                    rows.append({"user_id": data.get("user_id"), "label": data.get("display_name"), "active": 1})
                rows.extend({"user_id": data.get("user_id"), "label": alias, "active": 1} for alias in _loads_aliases(data.get("aliases_json")))
        if _table_exists(conn, "social_alias_name_index"):
            rows.extend(dict(row) for row in conn.execute("SELECT * FROM social_alias_name_index WHERE COALESCE(active, 1)=1").fetchall())
        return rows


def _count_active_mismatches(legacy_rows: list[dict], shadow_memories: list[MemoryRecord], issues: list[ShadowParityIssue]) -> int:
    shadow_by_id = {record.memory_id: record for record in shadow_memories}
    count = 0
    for row in legacy_rows:
        legacy_id = str(row.get("id") or row.get("memory_id") or "")
        legacy_active = bool(int(row.get("is_active") if row.get("is_active") is not None else 1))
        shadow = shadow_by_id.get(legacy_id)
        if shadow is None or shadow.is_active != legacy_active:
            count += 1
            issues.append(ShadowParityIssue("active_memory_mismatch", legacy_id, shadow.memory_id if shadow else None, "error", "active flag differs between legacy and shadow"))
    return count


def _count_deleted_mismatches(legacy_rows: list[dict], shadow_memories: list[MemoryRecord], issues: list[ShadowParityIssue]) -> int:
    shadow_by_id = {record.memory_id: record for record in shadow_memories}
    count = 0
    for row in legacy_rows:
        legacy_id = str(row.get("id") or row.get("memory_id") or "")
        legacy_deleted = not bool(int(row.get("is_active") if row.get("is_active") is not None else 1))
        shadow = shadow_by_id.get(legacy_id)
        shadow_deleted = bool(shadow and not shadow.is_active)
        if shadow is None or shadow_deleted != legacy_deleted:
            count += 1
            issues.append(ShadowParityIssue("deleted_memory_mismatch", legacy_id, shadow.memory_id if shadow else None, "error", "deleted state differs between legacy and shadow"))
    return count


def _count_alias_mismatches(legacy_rows: list[dict], shadow_aliases: list[AliasNode], issues: list[ShadowParityIssue]) -> int:
    legacy_keys = {
        (str(row.get("user_id") or row.get("identity_id") or ""), _norm(str(row.get("label") or row.get("alias_value") or "")))
        for row in legacy_rows
        if str(row.get("label") or row.get("alias_value") or "").strip()
    }
    shadow_keys = {(node.identity_id, _norm(node.alias_value)) for node in shadow_aliases if node.active}
    missing = sorted(key for key in legacy_keys if key not in shadow_keys)
    for identity_id, alias_norm in missing:
        issues.append(ShadowParityIssue("alias_mismatch", _mask(identity_id), None, "warning", f"alias projection missing: {alias_norm}"))
    return len(missing)


def _count_owner_pollution_candidates(shadow_memories: list[MemoryRecord], issues: list[ShadowParityIssue]) -> int:
    count = 0
    for record in shadow_memories:
        text = f"{record.value_text} {record.evidence_text}"
        if OWNER_POLLUTION_RE.search(text):
            count += 1
            issues.append(ShadowParityIssue("owner_pollution_candidate", record.memory_id, record.memory_id, "warning", "owner-like wording is present in memory content; keep it out of persona context"))
    return count


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def _loads_aliases(value: object) -> list[str]:
    import json

    try:
        data = json.loads(str(value or "[]"))
        return [str(item) for item in data if str(item).strip()] if isinstance(data, list) else []
    except Exception:
        return []


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _mask(value: str) -> str:
    if not value:
        return ""
    return f"{value[:2]}...{value[-2:]}" if len(value) > 4 else "***"
