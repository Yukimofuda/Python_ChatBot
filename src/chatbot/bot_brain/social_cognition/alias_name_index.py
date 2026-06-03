from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Iterable

try:
    from src.chatbot.bot_brain.memory_decision_frame import SYSTEM_TRACE_RE
except Exception:  # pragma: no cover
    SYSTEM_TRACE_RE = re.compile(r"(管理员|数据库|系统记录|后台|检索|记录|source_type|confidence)", re.I)

OWNER_USER_ID = ""
PROTECTED_OWNER_RE = re.compile(r"(?:owner|master|主人|主子)", re.I)
LABEL_SOURCE_TYPES = {"admin_said", "self_said", "other_said", "system_migration", "manual_restore"}
LABEL_PREDICATES = {"alias", "nickname", "display_name", "name", "称呼", "昵称", "外号"}
LABEL_TAGS = {"alias", "nickname", "display_name", "name", "admin_confirmed", "称呼", "昵称", "外号"}

@dataclass(frozen=True)
class AliasNameCandidate:
    user_id: str
    label: str
    label_key: str
    label_type: str = "alias"
    display_name: str = ""
    group_id: str = ""
    source_type: str = ""
    confidence: float = 0.5
    priority: float = 0.5
    active: bool = True
    memory_id: str = ""
    reason: str = ""
    updated_at: str = ""


def normalize_label_key(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", "", text)
    return text.casefold()


def _safe_json_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    try:
        data = json.loads(str(value))
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    except Exception:
        pass
    return []


def is_label_like(value: str, *, max_len: int = 24) -> bool:
    """Structural policy for values allowed to become alias/display names.

    This is intentionally not a sample blacklist. A label must look like a short
    name/handle/nickname, not like a sentence, event, roleplay output, system
    provenance text, or memory-body fragment.
    """
    text = str(value or "").strip()
    if not (1 <= len(text) <= max_len):
        return False
    if SYSTEM_TRACE_RE.search(text):
        return False
    if PROTECTED_OWNER_RE.search(text) and str(text) not in {"owner", "owner"}:
        return False
    if re.search(r"[，。！？!?；;：:\n\r\t]|https?://|\[CQ:", text, re.I):
        return False
    if re.search(r"\s{2,}", text):
        return False
    # Labels can contain one small space in QQ cards/handles, but not multiple words forming a clause.
    if " " in text and len(text) > 16:
        return False
    # Full-clause signals. These are grammatical categories, not individual bad examples.
    clause_signals = r"(?:的人|这个|那个|一种|一条|一句|自己|大家|有人|别人|真的|就是|因为|所以|然后|但是|如果|今天|刚才|现在|正在|喜欢|讨厌|擅长|学习|记得|觉得|认为|说过|描述|发明|哭|笑|躲|memory|记录)"
    if len(text) > 8 and re.search(clause_signals, text, re.I):
        return False
    # Very long CJK-only strings without separators are more likely memory text than nickname.
    if len(text) > 10 and re.fullmatch(r"[\u4e00-\u9fff]+", text):
        return False
    return True


def _row_dict(row: Any, columns: Iterable[str] | None = None) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        cols = list(columns or [])
        return {cols[i]: row[i] for i in range(min(len(cols), len(row)))}


def _query_rows(store: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    store.initialize()
    with store.connect() as conn:
        cur = conn.execute(sql, params)
        cols = [d[0] for d in (cur.description or [])]
        return [_row_dict(row, cols) for row in cur.fetchall()]


def _table_exists(store: Any, table: str) -> bool:
    try:
        rows = _query_rows(store, "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        return bool(rows)
    except Exception:
        return False


def _columns(store: Any, table: str) -> set[str]:
    try:
        rows = _query_rows(store, f"PRAGMA table_info({table})")
        return {str(r.get("name") or r.get(1) or "") for r in rows}
    except Exception:
        return set()


def _user_rows(store: Any) -> list[dict[str, Any]]:
    if not _table_exists(store, "social_users"):
        return []
    return _query_rows(store, "SELECT * FROM social_users")


def _active_memory_rows(store: Any) -> list[dict[str, Any]]:
    if not _table_exists(store, "social_memories"):
        return []
    cols = _columns(store, "social_memories")
    if "is_active" in cols:
        return _query_rows(store, "SELECT * FROM social_memories WHERE COALESCE(is_active, 1)=1")
    return _query_rows(store, "SELECT * FROM social_memories")


def _extract_alias_from_text(text: str) -> str:
    raw = str(text or "").strip()
    patterns = (
        r"(?:被称作|被叫作|通常被叫作|大家(?:通常|一般)?叫|外号是|昵称是)[“\"']?([^”\"'，。；;\s]{1,24})[”\"']?",
        r"(?:叫我|我叫|可以叫我)\s*([A-Za-z0-9_\-\u4e00-\u9fff·・ー]{1,24})",
    )
    for pat in patterns:
        m = re.search(pat, raw, re.I)
        if m:
            value = m.group(1).strip()
            if is_label_like(value, max_len=16):
                return value
    return ""


def _row_scope(row: dict[str, Any]) -> str:
    return str(row.get("scope_id") or row.get("group_id") or row.get("group") or "").strip()


def iter_alias_name_candidates(store: Any) -> list[AliasNameCandidate]:
    """Build an in-memory clean alias/name index from strong identity evidence.

    Strong evidence means social_users.display_name/aliases_json or memory rows
    whose predicate/tags explicitly mark them as alias/name/nickname. Arbitrary
    memory body matches are intentionally ignored.
    """
    candidates: list[AliasNameCandidate] = []
    seen: set[tuple[str, str, str, str]] = set()

    for row in _user_rows(store):
        uid = str(row.get("user_id") or row.get("subject_user_id") or "").strip()
        if not uid:
            continue
        scope = _row_scope(row)
        display = str(row.get("display_name") or row.get("nickname") or row.get("card") or "").strip()
        labels: list[tuple[str, str, float, str]] = []
        if is_label_like(display, max_len=20):
            labels.append((display, "display_name", 1.0, "social_users.display_name"))
        for alias in _safe_json_list(row.get("aliases_json") or row.get("aliases")):
            if is_label_like(alias, max_len=16):
                labels.append((alias, "alias", 0.95, "social_users.aliases"))
        for label, typ, score, reason in labels:
            key = normalize_label_key(label)
            ident = (uid, scope, key, typ)
            if ident in seen:
                continue
            seen.add(ident)
            candidates.append(AliasNameCandidate(uid, label, key, typ, display_name=display, group_id=scope, source_type="social_users", confidence=score, priority=score, active=True, reason=reason))

    for row in _active_memory_rows(store):
        uid = str(row.get("subject_user_id") or row.get("user_id") or "").strip()
        if not uid:
            continue
        predicate = str(row.get("predicate") or row.get("relation") or "").strip().casefold()
        tags = set(t.casefold() for t in _safe_json_list(row.get("tags_json") or row.get("tags")))
        source_type = str(row.get("source_type") or "").strip()
        text = str(row.get("memory_text") or row.get("raw_evidence") or "")
        value = str(row.get("value") or row.get("object") or "").strip()
        has_type_evidence = predicate in LABEL_PREDICATES or bool(tags & LABEL_TAGS)
        if not has_type_evidence:
            continue
        label = value if is_label_like(value, max_len=16) else _extract_alias_from_text(text)
        if not is_label_like(label, max_len=16):
            continue
        scope = _row_scope(row)
        conf = float(row.get("confidence") or 0.75)
        pri = float(row.get("priority") or 0.75)
        typ = "display_name" if predicate == "display_name" else ("nickname" if predicate == "nickname" else "alias")
        key = normalize_label_key(label)
        ident = (uid, scope, key, typ)
        if ident in seen:
            continue
        seen.add(ident)
        candidates.append(AliasNameCandidate(uid, label, key, typ, group_id=scope, source_type=source_type, confidence=conf, priority=pri, active=True, memory_id=str(row.get("id") or row.get("memory_id") or ""), reason="typed_social_memory", updated_at=str(row.get("updated_at") or row.get("created_at") or "")))
    return candidates


def search_alias_name_index(store: Any, terms: list[str], *, scope_id: str = "", top_k: int = 12) -> list[AliasNameCandidate]:
    keys = {normalize_label_key(t) for t in terms if is_label_like(t, max_len=16)}
    if not keys:
        return []
    scope = str(scope_id or "").strip()
    found = [c for c in iter_alias_name_candidates(store) if c.label_key in keys and (not scope or not c.group_id or c.group_id == scope)]
    def rank(c: AliasNameCandidate) -> tuple[float, float, float, str]:
        same_scope = 1.0 if scope and c.group_id == scope else 0.0
        type_score = {"display_name": 1.0, "alias": 0.95, "nickname": 0.93}.get(c.label_type, 0.8)
        return (-same_scope, -type_score, -(float(c.confidence) + float(c.priority)), c.display_name or c.label or c.user_id)
    found.sort(key=rank)
    # Deduplicate same user; keep best match per user.
    out: list[AliasNameCandidate] = []
    seen_user: set[str] = set()
    for c in found:
        if c.user_id in seen_user:
            continue
        seen_user.add(c.user_id)
        out.append(c)
        if len(out) >= top_k:
            break
    return out


def ensure_alias_name_index_table(store: Any) -> None:
    store.initialize()
    with store.connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS social_alias_name_index (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                group_id TEXT,
                label TEXT NOT NULL,
                label_key TEXT NOT NULL,
                label_type TEXT NOT NULL,
                display_name TEXT,
                source_type TEXT,
                confidence REAL DEFAULT 0.5,
                priority REAL DEFAULT 0.5,
                memory_id TEXT,
                active INTEGER DEFAULT 1,
                reason TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_social_alias_name_key ON social_alias_name_index(label_key, group_id, active)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_social_alias_name_user ON social_alias_name_index(user_id)")


def rebuild_alias_name_index(store: Any, *, dry_run: bool = False) -> dict[str, Any]:
    candidates = iter_alias_name_candidates(store)
    if dry_run:
        return {"candidate_count": len(candidates), "written": 0, "candidates": [c.__dict__ for c in candidates[:50]]}
    ensure_alias_name_index_table(store)
    now = str(int(time.time()))
    with store.connect() as conn:
        conn.execute("DELETE FROM social_alias_name_index")
        written = 0
        for i, c in enumerate(candidates):
            ident = f"alias_{c.user_id}_{c.group_id}_{c.label_key}_{c.label_type}_{i}"
            conn.execute(
                """
                INSERT OR REPLACE INTO social_alias_name_index
                (id, user_id, group_id, label, label_key, label_type, display_name, source_type, confidence, priority, memory_id, active, reason, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (ident, c.user_id, c.group_id, c.label, c.label_key, c.label_type, c.display_name, c.source_type, c.confidence, c.priority, c.memory_id, 1 if c.active else 0, c.reason, c.updated_at or now),
            )
            written += 1
    return {"candidate_count": len(candidates), "written": written}


def inspect_alias(store: Any, term: str, *, scope_id: str = "", top_k: int = 20) -> list[dict[str, Any]]:
    return [c.__dict__ for c in search_alias_name_index(store, [term], scope_id=scope_id, top_k=top_k)]
