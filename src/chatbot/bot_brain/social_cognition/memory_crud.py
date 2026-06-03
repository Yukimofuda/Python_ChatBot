from __future__ import annotations

"""Auditable CRUD control plane for social memories.

This module is intentionally policy driven:
- Create: write a typed memory row only after structural validation.
- Read: return governed/sanitized rows, never raw DB text as final output.
- Update: keep the same memory_id but write a revision/audit row first.
- Delete: soft-delete by memory_id or governed term match; never pretend success.

It does not use sample-specific bad-word patches. The invariant is that every
operator-visible mutation is auditable and every alias/name mutation can be
re-derived by the clean alias/name index.
"""

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

try:
    from .memory_governance import classify_memory_row, inspect_user_governed, is_safe_label, resolve_user_id
except Exception:  # pragma: no cover - test/import fallback
    classify_memory_row = None  # type: ignore
    inspect_user_governed = None  # type: ignore
    is_safe_label = None  # type: ignore
    resolve_user_id = None  # type: ignore

LABEL_TAGS = {"alias", "nickname", "display_name", "name", "称呼", "昵称", "外号"}
PROFILE_TAGS = {"profile", "skill", "preference", "habit", "identity_role", "self_profile", "admin_confirmed"}
VALID_ACTIONS = {"create", "read", "update", "soft_delete", "restore"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _clean(text: str) -> str:
    text = str(text or "").replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
    return re.sub(r"\s+", " ", text).strip()


def _normalize_subject_ref(ref: str) -> str:
    raw = _clean(ref).translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    m = re.search(r"\[CQ:at,qq=(\d{5,12})\]", raw)
    if m:
        return m.group(1)
    m = re.search(r"@\s*(\d{5,12})", raw)
    if m:
        return m.group(1)
    if re.fullmatch(r"\d{5,12}", raw):
        return raw
    nums = re.findall(r"(?<!\d)(\d{5,12})(?!\d)", raw)
    if len(nums) == 1:
        return nums[0]
    return raw


def _clip(text: str, limit: int) -> str:
    return _clean(text)[:limit]


def _normalize_tag(tag: str) -> str:
    t = str(tag or "").strip().casefold()
    aliases = {"nick": "nickname", "display": "display_name", "用户名": "display_name", "昵称": "nickname", "外号": "alias", "称呼": "alias"}
    return aliases.get(t, t)


def normalize_tags(tags: Iterable[str] | str | None, *, admin_confirmed: bool = True) -> list[str]:
    if tags is None:
        items: list[str] = []
    elif isinstance(tags, str):
        items = [x for x in re.split(r"[,，/\s]+", tags) if x]
    else:
        items = [str(x) for x in tags if str(x).strip()]
    out = []
    for item in items:
        tag = _normalize_tag(item)
        if tag and re.fullmatch(r"[a-z0-9_\-\u4e00-\u9fff]{1,32}", tag, re.I):
            out.append(tag)
    if admin_confirmed and "admin_confirmed" not in out:
        out.append("admin_confirmed")
    if not (set(out) & (LABEL_TAGS | PROFILE_TAGS)):
        out.append("profile")
    return list(dict.fromkeys(out))[:12]


def is_label_memory(tags: Iterable[str] | None) -> bool:
    return bool({str(t).casefold() for t in (tags or [])} & LABEL_TAGS)


def canonical_memory_text(text: str, tags: Iterable[str] | None = None) -> str:
    raw = _clean(text)
    if not raw:
        return ""
    tag_set = {str(t).casefold() for t in (tags or [])}
    if tag_set & LABEL_TAGS:
        label = extract_label_value(raw) or raw
        return f"该群友通常被叫作“{label}”"
    # Avoid forcing a schema; profile facts stay as human-readable fact text.
    return raw


def extract_label_value(text: str) -> str:
    raw = _clean(text)
    patterns = (
        r"[“\"']([^”\"'，。；;\s]{1,24})[”\"']",
        r"(?:被称作|被叫作|通常被叫作|大家叫|外号是|昵称是|叫作|称作)\s*([A-Za-z0-9_\-\u4e00-\u9fff·・ー]{1,24})",
        r"^([A-Za-z0-9_\-\u4e00-\u9fff·・ー]{1,24})$",
    )
    for pat in patterns:
        m = re.search(pat, raw, re.I)
        if m:
            label = m.group(1).strip()
            if is_crud_label_value(label):
                return label
    return ""



PROFILE_SYSTEM_TRACE_RE = re.compile(
    r"(数据库|系统记录|plugin|插件输出|prompt|system prompt|上下文|memory body|profile_summary|审计|audit|日志|log)",
    re.I,
)
PROFILE_TRANSIENT_RE = re.compile(
    r"^(今天|刚才|刚刚|现在|此刻|昨天|明天|今晚|早上|中午|晚上).{0,24}(哭|笑|睡|吃|说|发|来了|走了|上线|下线|重启|报错|生气|开心)",
    re.I,
)
PROFILE_COMMAND_RE = re.compile(r"^\s*(/|!|！|#|＃|删除|新增|修改|查询|inspect|memory\s+)", re.I)



LABEL_SENTENCE_RE = re.compile(
    r"(一句话|里面|很多|自己|今天|昨天|明天|刚才|正在|已经|因为|所以|觉得|认为|喜欢.+和.+|会或擅长|memory|数据库|记录|系统|prompt|插件)",
    re.I,
)
LABEL_VERB_PHRASE_RE = re.compile(r"(在.+?(哭|笑|睡|吃|说|发|写|修|跑|报错|重启)|是.+?的.+?人|大家都说|管理员确认)", re.I)


def is_crud_label_value(label: str) -> bool:
    value = _clean(label)
    if not value:
        return False
    if len(value) > 16:
        return False
    if re.search(r"[。！？!?，,；;：:]", value):
        return False
    if LABEL_SENTENCE_RE.search(value) or LABEL_VERB_PHRASE_RE.search(value):
        return False
    if is_safe_label is not None and not is_safe_label(value, max_len=16):
        return False
    return bool(re.search(r"[A-Za-z0-9\u4e00-\u9fff\u3040-\u30ff]", value))


def is_stable_profile_fact(text: str) -> tuple[bool, str]:
    """Validate non-label social memory facts.

    This is deliberately separate from alias/display-name label validation.
    A stable profile fact may be a short natural sentence such as
    “喜欢 Python 和修 bot”; it must not be forced through label-like rules.
    """
    raw = _clean(text)
    if not raw:
        return False, "empty_profile_fact"
    if len(raw) > 220:
        return False, "profile_fact_too_long"
    if PROFILE_COMMAND_RE.search(raw):
        return False, "command_like_profile_fact"
    if PROFILE_SYSTEM_TRACE_RE.search(raw):
        return False, "system_trace_profile_fact"
    if PROFILE_TRANSIENT_RE.search(raw):
        return False, "transient_event_profile_fact"
    # Require at least some semantic content. This permits Chinese/Japanese/English
    # profile facts, preferences, skills and habits while rejecting punctuation noise.
    if not re.search(r"[A-Za-z0-9\u4e00-\u9fff\u3040-\u30ff]", raw):
        return False, "no_semantic_content"
    return True, "stable_profile_fact"


def validate_memory_write(mem_text: str, tags: Iterable[str] | None, *, row_probe: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Typed write gate for CRUD.

    - alias/nickname/display_name memories use strict label-like validation.
    - profile/preference/skill/habit facts use stable-fact validation.
    - governance classify_memory_row may still veto labels and profile facts, but
      label failures must not be applied to normal profile facts.
    """
    norm = [str(t).casefold() for t in (tags or [])]
    if is_label_memory(norm):
        label = extract_label_value(mem_text)
        if not label:
            return False, "invalid_label_value"
        if not is_crud_label_value(label):
            return False, "invalid_label_value"
        if classify_memory_row is not None and row_probe is not None:
            decision = classify_memory_row(dict(row_probe, value=label))
            if not decision.renderable and decision.quarantine:
                return False, ",".join(decision.reasons) or "label_governance_rejected"
        return True, "valid_label_memory"
    ok, reason = is_stable_profile_fact(mem_text)
    if not ok:
        return False, reason
    if classify_memory_row is not None and row_probe is not None:
        decision = classify_memory_row(dict(row_probe, value=""))
        # Only honor governance vetoes that are not label-value failures. Some old
        # governance code treats every row as if it had a label; CRUD must not.
        reasons = set(decision.reasons or ())
        if (not decision.renderable and decision.quarantine) and not reasons <= {"invalid_label_value"}:
            return False, ",".join(decision.reasons) or "profile_governance_rejected"
    return True, "valid_profile_memory"


def ensure_crud_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS social_memory_crud_audit (
            id TEXT PRIMARY KEY,
            action TEXT NOT NULL,
            memory_id TEXT,
            subject_user_id TEXT,
            actor_user_id TEXT,
            scope_id TEXT,
            before_json TEXT,
            after_json TEXT,
            reason TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS social_memory_revisions (
            id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            revision_no INTEGER NOT NULL,
            subject_user_id TEXT,
            old_row_json TEXT,
            new_row_json TEXT,
            actor_user_id TEXT,
            reason TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_social_memory_crud_audit_memory ON social_memory_crud_audit(memory_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_social_memory_revisions_memory ON social_memory_revisions(memory_id, revision_no)")


def _row_to_dict(row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return {}
    return dict(row) if not isinstance(row, dict) else dict(row)


def _audit(conn: sqlite3.Connection, *, action: str, memory_id: str = "", subject_user_id: str = "", actor_user_id: str = "", scope_id: str = "", before: Any = None, after: Any = None, reason: str = "") -> None:
    if action not in VALID_ACTIONS:
        action = str(action or "unknown")[:32]
    conn.execute(
        """
        INSERT INTO social_memory_crud_audit(id, action, memory_id, subject_user_id, actor_user_id, scope_id, before_json, after_json, reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"crud_{uuid.uuid4().hex}",
            action,
            str(memory_id or ""),
            str(subject_user_id or ""),
            str(actor_user_id or ""),
            str(scope_id or ""),
            _json_dumps(before or {}),
            _json_dumps(after or {}),
            str(reason or ""),
            utc_now(),
        ),
    )


def _next_revision_no(conn: sqlite3.Connection, memory_id: str) -> int:
    row = conn.execute("SELECT COALESCE(MAX(revision_no), 0) + 1 FROM social_memory_revisions WHERE memory_id=?", (memory_id,)).fetchone()
    return int(row[0] if row else 1)


def _revision(conn: sqlite3.Connection, *, memory_id: str, old_row: dict[str, Any], new_row: dict[str, Any], actor_user_id: str = "", reason: str = "") -> None:
    conn.execute(
        """
        INSERT INTO social_memory_revisions(id, memory_id, revision_no, subject_user_id, old_row_json, new_row_json, actor_user_id, reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"rev_{uuid.uuid4().hex}",
            memory_id,
            _next_revision_no(conn, memory_id),
            str(old_row.get("subject_user_id") or new_row.get("subject_user_id") or ""),
            _json_dumps(old_row),
            _json_dumps(new_row),
            str(actor_user_id or ""),
            reason,
            utc_now(),
        ),
    )


def _apply_alias_to_social_user(conn: sqlite3.Connection, subject_user_id: str, label: str, *, display: bool = False) -> None:
    uid = str(subject_user_id or "").strip()
    label = str(label or "").strip()
    if not uid or not label:
        return
    if is_safe_label is not None and not is_safe_label(label, max_len=16):
        return
    now = utc_now()
    row = conn.execute("SELECT display_name, aliases_json FROM social_users WHERE user_id=?", (uid,)).fetchone()
    if row:
        aliases = set(_json_loads(row["aliases_json"], []))
        aliases.add(label)
        final_display = label if display else (str(row["display_name"] or "") or label)
        conn.execute(
            "UPDATE social_users SET display_name=?, aliases_json=?, last_seen_at=? WHERE user_id=?",
            (final_display, _json_dumps(sorted(aliases - {uid})), now, uid),
        )
    else:
        conn.execute(
            """
            INSERT INTO social_users(user_id, display_name, aliases_json, first_seen_at, last_seen_at, profile_summary, profile_updated_at)
            VALUES (?, ?, ?, ?, ?, '', '')
            """,
            (uid, label if display else label, _json_dumps([label]), now, now),
        )


def _resolve_subject(store: Any, subject_ref: str) -> str:
    ref = _normalize_subject_ref(subject_ref)
    if re.fullmatch(r"\d{5,12}", ref):
        return ref
    if re.fullmatch(r"\d+", ref):
        try:
            with store.connect() as conn:
                row = conn.execute("SELECT user_id FROM social_users WHERE user_id=?", (ref,)).fetchone()
                if row:
                    return str(row["user_id"] if hasattr(row, "keys") else row[0])
        except Exception:
            pass
    if resolve_user_id is not None:
        uid = resolve_user_id(store, ref)
        if uid:
            return str(uid)
    try:
        uid = store.resolve_user_reference(ref)
        return str(uid or "")
    except Exception:
        return ""


@dataclass(frozen=True)
class CrudResult:
    ok: bool
    message: str
    memory_id: str = ""
    updated: int = 0
    rows: tuple[dict[str, Any], ...] = ()


class SocialMemoryCrud:
    def __init__(self, store: Any) -> None:
        self.store = store

    def create(self, *, subject_ref: str, text: str, actor_user_id: str = "", scope_id: str = "", tags: Iterable[str] | str | None = None, source_type: str = "admin_crud", confidence: float = 0.92, priority: float = 0.86) -> CrudResult:
        if hasattr(self.store, "initialize"):
            self.store.initialize()
        uid = _resolve_subject(self.store, subject_ref)
        if not uid:
            return CrudResult(False, "没对上要新增记忆的群友；请用 账号 ID、@ 或明确昵称。")
        norm_tags = normalize_tags(tags)
        mem_text = canonical_memory_text(text, norm_tags)
        if not mem_text:
            return CrudResult(False, "新增记忆内容为空。")
        probe = {"id": "probe", "subject_user_id": uid, "memory_text": mem_text, "value": extract_label_value(mem_text) if is_label_memory(norm_tags) else "", "tags_json": _json_dumps(norm_tags), "source_type": source_type, "confidence": confidence, "priority": priority}
        valid, reason = validate_memory_write(mem_text, norm_tags, row_probe=probe)
        if not valid:
            return CrudResult(False, "这条内容不符合可写入的稳定画像/称呼策略，未新增。原因：" + reason)
        mid = f"smem_{uuid.uuid4().hex}"
        now = utc_now()
        try:
            with self.store.connect() as conn:
                ensure_crud_tables(conn)
                conn.execute(
                    """
                    INSERT INTO social_memories(
                        id, subject_user_id, source_user_id, scope_id, source_type, memory_text, raw_evidence,
                        confidence, priority, emotion_valence, tags_json, created_at, updated_at, decay, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, ?, ?, ?, 1.0, 1)
                    """,
                    (mid, uid, str(actor_user_id or ""), str(scope_id or ""), source_type, _clip(mem_text, 500), _clip(text, 700), float(confidence), float(priority), _json_dumps(norm_tags), now, now),
                )
                label = extract_label_value(mem_text) if is_label_memory(norm_tags) else ""
                if label:
                    _apply_alias_to_social_user(conn, uid, label, display="display_name" in {t.casefold() for t in norm_tags})
                after = {"id": mid, "subject_user_id": uid, "memory_text": mem_text, "tags": norm_tags, "is_active": 1}
                _audit(conn, action="create", memory_id=mid, subject_user_id=uid, actor_user_id=actor_user_id, scope_id=scope_id, after=after, reason="admin_crud_create")
            return CrudResult(True, f"已新增 1 条记忆：{mid}", memory_id=mid, updated=1)
        except sqlite3.Error as exc:
            return CrudResult(False, f"新增记忆失败：{exc}")

    def list(self, *, subject_ref: str, include_hidden: bool = False, limit: int = 20) -> CrudResult:
        if hasattr(self.store, "initialize"):
            self.store.initialize()
        uid = _resolve_subject(self.store, subject_ref)
        if not uid:
            return CrudResult(False, "没对上要查询的群友。")
        sql = "SELECT * FROM social_memories WHERE subject_user_id=?"
        args: list[Any] = [uid]
        if not include_hidden:
            sql += " AND COALESCE(is_active, 1)=1"
        sql += " ORDER BY updated_at DESC LIMIT ?"
        args.append(int(limit))
        with self.store.connect() as conn:
            ensure_crud_tables(conn)
            rows = [_row_to_dict(r) for r in conn.execute(sql, args).fetchall()]
            governed: list[dict[str, Any]] = []
            for row in rows:
                tags = _json_loads(row.get("tags_json"), [])
                row["tags"] = tags
                if classify_memory_row is not None:
                    d = classify_memory_row(row)
                    tags_set = {str(t).casefold() for t in tags}
                    display_text = d.display_text or _clean(str(row.get("memory_text") or ""))
                    renderable = bool(d.renderable)
                    if (not renderable) and str(row.get("source_type") or "").startswith("admin_crud") and tags_set & {"profile", "skill", "preference", "habit", "admin_confirmed"}:
                        # Typed CRUD profile facts have already passed write-gate; old governance label checks must not hide them.
                        renderable = True
                    row["governance"] = {"renderable": renderable, "quarantine": bool(d.quarantine and not renderable), "reasons": list(d.reasons), "display_text": display_text}
                governed.append(row)
            _audit(conn, action="read", subject_user_id=uid, after={"count": len(governed), "include_hidden": include_hidden}, reason="admin_crud_read")
        return CrudResult(True, f"查到 {len(governed)} 条记忆。", rows=tuple(governed))

    def update(self, *, memory_id: str, new_text: str, actor_user_id: str = "", tags: Iterable[str] | str | None = None, reason: str = "admin_crud_update") -> CrudResult:
        mid = str(memory_id or "").strip()
        if not mid:
            return CrudResult(False, "缺少 memory_id。")
        if hasattr(self.store, "initialize"):
            self.store.initialize()
        try:
            with self.store.connect() as conn:
                ensure_crud_tables(conn)
                old = _row_to_dict(conn.execute("SELECT * FROM social_memories WHERE id=?", (mid,)).fetchone())
                if not old:
                    return CrudResult(False, "没有找到这个 memory_id。")
                old_tags = _json_loads(old.get("tags_json"), [])
                norm_tags = normalize_tags(tags if tags is not None else old_tags)
                mem_text = canonical_memory_text(new_text, norm_tags)
                probe = dict(old)
                probe.update({"memory_text": mem_text, "raw_evidence": new_text, "tags_json": _json_dumps(norm_tags), "value": extract_label_value(mem_text) if is_label_memory(norm_tags) else ""})
                valid, reason = validate_memory_write(mem_text, norm_tags, row_probe=probe)
                if not valid:
                    return CrudResult(False, "修改后的内容不符合稳定画像/称呼策略，未写入。原因：" + reason)
                now = utc_now()
                conn.execute(
                    """
                    UPDATE social_memories
                    SET memory_text=?, raw_evidence=?, tags_json=?, source_user_id=?, updated_at=?, decay=1.0, is_active=1
                    WHERE id=?
                    """,
                    (_clip(mem_text, 500), _clip(new_text, 700), _json_dumps(norm_tags), str(actor_user_id or old.get("source_user_id") or ""), now, mid),
                )
                new = _row_to_dict(conn.execute("SELECT * FROM social_memories WHERE id=?", (mid,)).fetchone())
                _revision(conn, memory_id=mid, old_row=old, new_row=new, actor_user_id=actor_user_id, reason=reason)
                _audit(conn, action="update", memory_id=mid, subject_user_id=str(old.get("subject_user_id") or ""), actor_user_id=actor_user_id, scope_id=str(old.get("scope_id") or ""), before=old, after=new, reason=reason)
                label = extract_label_value(mem_text) if is_label_memory(norm_tags) else ""
                if label:
                    _apply_alias_to_social_user(conn, str(old.get("subject_user_id") or ""), label, display="display_name" in {t.casefold() for t in norm_tags})
            return CrudResult(True, f"已修改记忆：{mid}", memory_id=mid, updated=1)
        except sqlite3.Error as exc:
            return CrudResult(False, f"修改记忆失败：{exc}")

    def soft_delete(self, *, memory_id: str = "", subject_ref: str = "", terms: Iterable[str] | None = None, actor_user_id: str = "", reason: str = "admin_crud_soft_delete") -> CrudResult:
        if hasattr(self.store, "initialize"):
            self.store.initialize()
        term_list = [_clean(t) for t in (terms or []) if _clean(t)]
        try:
            with self.store.connect() as conn:
                ensure_crud_tables(conn)
                rows: list[dict[str, Any]] = []
                if memory_id:
                    row = _row_to_dict(conn.execute("SELECT * FROM social_memories WHERE id=? AND COALESCE(is_active, 1)=1", (memory_id,)).fetchone())
                    if row:
                        rows = [row]
                else:
                    uid = _resolve_subject(self.store, subject_ref)
                    if not uid:
                        return CrudResult(False, "没对上要删除哪位群友的记忆。")
                    candidates = [_row_to_dict(r) for r in conn.execute("SELECT * FROM social_memories WHERE subject_user_id=? AND COALESCE(is_active, 1)=1", (uid,)).fetchall()]
                    if term_list:
                        rows = [r for r in candidates if any(t in str(r.get("memory_text") or "") or t in str(r.get("raw_evidence") or "") for t in term_list)]
                    else:
                        rows = candidates
                if not rows:
                    return CrudResult(False, "没有找到匹配的 active 记忆；不会假装删除。")
                now = utc_now()
                for row in rows:
                    mid = str(row.get("id") or "")
                    conn.execute("UPDATE social_memories SET is_active=0, updated_at=? WHERE id=?", (now, mid))
                    new_row = dict(row)
                    new_row["is_active"] = 0
                    new_row["updated_at"] = now
                    _revision(conn, memory_id=mid, old_row=row, new_row=new_row, actor_user_id=actor_user_id, reason=reason)
                    _audit(conn, action="soft_delete", memory_id=mid, subject_user_id=str(row.get("subject_user_id") or ""), actor_user_id=actor_user_id, scope_id=str(row.get("scope_id") or ""), before=row, after=new_row, reason=reason)
            return CrudResult(True, f"已软删除 {len(rows)} 条记忆，并写入审计。", updated=len(rows), rows=tuple(rows))
        except sqlite3.Error as exc:
            return CrudResult(False, f"删除记忆失败：{exc}")

    def restore(self, *, memory_id: str, actor_user_id: str = "", reason: str = "admin_crud_restore") -> CrudResult:
        mid = str(memory_id or "").strip()
        if not mid:
            return CrudResult(False, "缺少 memory_id。")
        if hasattr(self.store, "initialize"):
            self.store.initialize()
        try:
            with self.store.connect() as conn:
                ensure_crud_tables(conn)
                old = _row_to_dict(conn.execute("SELECT * FROM social_memories WHERE id=?", (mid,)).fetchone())
                if not old:
                    return CrudResult(False, "没有找到这个 memory_id。")
                conn.execute("UPDATE social_memories SET is_active=1, updated_at=? WHERE id=?", (utc_now(), mid))
                new = _row_to_dict(conn.execute("SELECT * FROM social_memories WHERE id=?", (mid,)).fetchone())
                _revision(conn, memory_id=mid, old_row=old, new_row=new, actor_user_id=actor_user_id, reason=reason)
                _audit(conn, action="restore", memory_id=mid, subject_user_id=str(old.get("subject_user_id") or ""), actor_user_id=actor_user_id, before=old, after=new, reason=reason)
            return CrudResult(True, f"已恢复记忆：{mid}", memory_id=mid, updated=1)
        except sqlite3.Error as exc:
            return CrudResult(False, f"恢复记忆失败：{exc}")

    def audit_log(self, *, memory_id: str = "", subject_ref: str = "", limit: int = 20) -> CrudResult:
        if hasattr(self.store, "initialize"):
            self.store.initialize()
        with self.store.connect() as conn:
            ensure_crud_tables(conn)
            if memory_id:
                rows = [_row_to_dict(r) for r in conn.execute("SELECT * FROM social_memory_crud_audit WHERE memory_id=? ORDER BY created_at DESC LIMIT ?", (memory_id, int(limit))).fetchall()]
            elif subject_ref:
                uid = _resolve_subject(self.store, subject_ref)
                rows = [_row_to_dict(r) for r in conn.execute("SELECT * FROM social_memory_crud_audit WHERE subject_user_id=? ORDER BY created_at DESC LIMIT ?", (uid, int(limit))).fetchall()] if uid else []
            else:
                rows = [_row_to_dict(r) for r in conn.execute("SELECT * FROM social_memory_crud_audit ORDER BY created_at DESC LIMIT ?", (int(limit),)).fetchall()]
        return CrudResult(True, f"查到 {len(rows)} 条审计记录。", rows=tuple(rows))


def format_crud_rows(rows: Iterable[dict[str, Any]], *, show_hidden: bool = False) -> str:
    lines: list[str] = []
    for row in rows:
        mid = str(row.get("id") or "")
        active = int(row.get("is_active") if row.get("is_active") is not None else 1)
        if not show_hidden and not active:
            continue
        gov = row.get("governance") or {}
        display = gov.get("display_text") or _clean(str(row.get("memory_text") or ""))
        status = "active" if active else "inactive"
        if gov:
            status += ", renderable" if gov.get("renderable") else ", hidden"
        lines.append(f"- {mid} [{status}] {display}")
    return "\n".join(lines) if lines else "没有可展示的记忆。"
