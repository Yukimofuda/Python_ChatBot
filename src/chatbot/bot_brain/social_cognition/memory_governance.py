from __future__ import annotations

"""Governance layer for social cognition memories.

This module is deliberately policy/type driven, not sample-blacklist driven.
It provides one shared path for:
- admin inspection
- quarantine/migration
- natural-language admin deletion
- output sanitation

The invariant is: raw social_memories are never rendered directly. Every row is
classified first, and unsafe rows are either hidden, quarantined, or soft-deleted
with an audit record.
"""

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

OWNER_USER_ID = ""

SYSTEM_TRACE_RE = re.compile(
    r"(?:数据库|系统记录|后台|检索|索引|source_type|confidence|priority|memory_id|raw_evidence|audit|管理员确认|记录)",
    re.I,
)
PROTECTED_OWNER_RE = re.compile(r"(?:owner|master|主人|主子)", re.I)
TRANSIENT_EVENT_RE = re.compile(
    r"(?:今天|刚才|现在|正在|刚刚|一会儿|被窝|哭了|签到|天气|B站|视频解析|生成图片|指令|命令|/|https?://|CQ:)",
    re.I,
)
ROLEPLAY_OR_PLUGIN_RE = re.compile(r"(?:扮演|角色扮演|系统提示|prompt|插件|plugin|LLM|模型输出|回复说|bot说)", re.I)
STABLE_PROFILE_RE = re.compile(
    r"(?:喜欢|讨厌|不喜欢|会|擅长|正在学|学习|经常|平时|习惯|外号|昵称|通常被叫|被叫作|被称作|是.*(?:学生|老师|群友|管理员|开发者|画师|程序员))",
    re.I,
)
LABEL_PREDICATES = {"alias", "nickname", "display_name", "name", "称呼", "昵称", "外号"}
LABEL_TAGS = {"alias", "nickname", "display_name", "name", "称呼", "昵称", "外号"}
UNSAFE_TAGS = {"command", "plugin_output", "llm_output", "roleplay", "transient_event", "system_trace", "owner_pollution"}
PROFILE_RENDER_TAGS = {"skill", "preference", "habit", "profile", "identity_role", "self_profile", "admin_confirmed"}


@dataclass(frozen=True)
class MemoryGovernanceDecision:
    memory_id: str
    subject_user_id: str
    renderable: bool
    quarantine: bool
    reasons: tuple[str, ...]
    display_text: str = ""
    priority: float = 0.0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _clean_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _normalize_key(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).casefold()


def is_safe_label(value: str, *, max_len: int = 20) -> bool:
    """Structural label policy for display_name/alias/nickname values."""
    text = str(value or "").strip()
    if not (1 <= len(text) <= max_len):
        return False
    if SYSTEM_TRACE_RE.search(text) or ROLEPLAY_OR_PLUGIN_RE.search(text):
        return False
    if PROTECTED_OWNER_RE.search(text) and text not in {"owner", "owner"}:
        return False
    if re.search(r"[，。！？!?；;：:\n\r\t]|https?://|\[CQ:", text, re.I):
        return False
    if " " in text and len(text) > 16:
        return False
    clause_signals = r"(?:的人|这个|那个|一种|一条|一句|自己|大家|有人|别人|真的|就是|因为|所以|然后|但是|如果|今天|刚才|现在|正在|喜欢|讨厌|擅长|学习|记得|觉得|认为|说过|描述|发明|哭|笑|躲|memory|记录)"
    if len(text) > 8 and re.search(clause_signals, text, re.I):
        return False
    if len(text) > 10 and re.fullmatch(r"[\u4e00-\u9fff]+", text):
        return False
    return True


def sanitize_display_name(value: str, fallback: str = "这位群友") -> str:
    text = str(value or "").strip()
    return text if is_safe_label(text, max_len=20) else fallback


def _strip_system_prefix(text: str) -> str:
    t = _clean_spaces(text)
    t = re.sub(r"^(?:管理员确认)?(?:该群友|这个群友|这个人|这人)(?:自述|被称作|被叫作)?[:：]?", "", t)
    t = re.sub(r"(?:该群友|这个群友|这个人|这人)自述[:：]?", "自己说过", t)
    t = re.sub(r"(?:该群友|这个群友|这个人|这人)", "", t)
    t = re.sub(r"有人(?:说|描述|提到)", "有人提过", t)
    return t.strip(" ，,。；;：:")


def _extract_label_from_alias_text(text: str) -> str:
    raw = str(text or "")
    patterns = (
        r"(?:被称作|被叫作|通常被叫作|大家(?:通常|一般)?叫|外号是|昵称是)[“\"']?([^”\"'，。；;\s]{1,24})[”\"']?",
        r"(?:叫我|我叫|可以叫我|我是)\s*([A-Za-z0-9_\-\u4e00-\u9fff·・ー]{1,24})",
    )
    for pat in patterns:
        m = re.search(pat, raw, re.I)
        if m:
            label = m.group(1).strip()
            if is_safe_label(label, max_len=16):
                return label
    return ""


def classify_memory_row(row: dict[str, Any]) -> MemoryGovernanceDecision:
    mid = str(row.get("id") or row.get("memory_id") or "")
    subject = str(row.get("subject_user_id") or row.get("user_id") or "")
    text = _clean_spaces(str(row.get("memory_text") or row.get("value") or ""))
    raw = _clean_spaces(str(row.get("raw_evidence") or ""))
    predicate = str(row.get("predicate") or row.get("relation") or "").strip().casefold()
    tags = {t.casefold() for t in _safe_json_list(row.get("tags_json") or row.get("tags"))}
    reasons: list[str] = []
    if not text:
        return MemoryGovernanceDecision(mid, subject, False, True, ("empty_memory",))
    if tags & UNSAFE_TAGS:
        reasons.append("unsafe_tag")
    if SYSTEM_TRACE_RE.search(text) or SYSTEM_TRACE_RE.search(raw):
        reasons.append("system_trace_or_provenance")
    if ROLEPLAY_OR_PLUGIN_RE.search(text) or ROLEPLAY_OR_PLUGIN_RE.search(raw):
        reasons.append("roleplay_or_plugin_output")
    if PROTECTED_OWNER_RE.search(text) and subject != OWNER_USER_ID:
        reasons.append("protected_owner_pollution")
    if TRANSIENT_EVENT_RE.search(text):
        reasons.append("transient_event_or_command")

    typed_label = predicate in LABEL_PREDICATES or bool(tags & LABEL_TAGS)
    if typed_label:
        label = str(row.get("value") or "").strip() or _extract_label_from_alias_text(text)
        if not is_safe_label(label, max_len=16):
            reasons.append("invalid_label_value")
        if reasons:
            return MemoryGovernanceDecision(mid, subject, False, True, tuple(dict.fromkeys(reasons)))
        return MemoryGovernanceDecision(mid, subject, True, False, (), f"通常被叫作“{label}”", float(row.get("priority") or 0.85))

    if reasons:
        return MemoryGovernanceDecision(mid, subject, False, True, tuple(dict.fromkeys(reasons)))

    clean = _strip_system_prefix(text)
    if not clean or SYSTEM_TRACE_RE.search(clean) or PROTECTED_OWNER_RE.search(clean):
        return MemoryGovernanceDecision(mid, subject, False, True, ("unsafe_after_cleaning",))
    if not (tags & PROFILE_RENDER_TAGS or STABLE_PROFILE_RE.search(clean)):
        return MemoryGovernanceDecision(mid, subject, False, True, ("not_stable_profile_fact",))
    clean = clean.replace("自己说过喜欢", "喜欢").replace("自己说过会", "会").replace("自己说过擅长", "擅长")
    clean = clean.strip(" ，,。；;：:")
    if not clean:
        return MemoryGovernanceDecision(mid, subject, False, True, ("empty_after_cleaning",))
    if len(clean) > 48:
        clean = clean[:47].rstrip("，、；;：: ") + "…"
    return MemoryGovernanceDecision(mid, subject, True, False, (), clean, float(row.get("priority") or 0.5))


def ensure_governance_audit_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS social_memory_governance_audit (
            id TEXT PRIMARY KEY,
            action TEXT NOT NULL,
            memory_id TEXT,
            subject_user_id TEXT,
            actor_user_id TEXT,
            reason TEXT,
            old_is_active INTEGER,
            new_is_active INTEGER,
            created_at TEXT NOT NULL
        )
        """
    )


def _fetch_user_row(conn: sqlite3.Connection, user_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM social_users WHERE user_id=?", (str(user_id),)).fetchone()
    return dict(row) if row else {"user_id": str(user_id), "display_name": "", "aliases_json": "[]"}


def _fetch_active_memories(conn: sqlite3.Connection, user_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM social_memories
        WHERE subject_user_id=? AND COALESCE(is_active, 1)=1
        ORDER BY (priority * 0.55 + confidence * 0.45) DESC, updated_at DESC
        """,
        (str(user_id),),
    ).fetchall()
    return [dict(r) for r in rows]


def resolve_user_id(store: Any, reference: str) -> str:
    ref = str(reference or "").strip().replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
    ref = ref.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    m = re.search(r"\[CQ:at,qq=(\d{5,12})\]", ref)
    if m:
        return m.group(1)
    nums = re.findall(r"(?<!\d)(\d{5,12})(?!\d)", ref)
    if len(nums) == 1:
        return nums[0]
    if re.fullmatch(r"\d{5,12}", ref):
        return ref
    try:
        uid = store.resolve_user_reference(ref)
        return str(uid or "")
    except Exception:
        return ""


def inspect_user_governed(store: Any, reference: str, *, include_policy_counts: bool = True) -> str:
    ref = str(reference or "").strip()
    if not ref:
        return "用法：/memory inspect <账号ID或昵称>"
    store.initialize()
    uid = resolve_user_id(store, ref)
    if not uid:
        return "还没找到这个群友的可靠记录。"
    with store.connect() as conn:
        user = _fetch_user_row(conn, uid)
        memories = _fetch_active_memories(conn, uid)
    display = sanitize_display_name(str(user.get("display_name") or ""), fallback=f"QQ {uid}")
    aliases = [a for a in _safe_json_list(user.get("aliases_json")) if is_safe_label(a, max_len=16)]
    decisions = [classify_memory_row(row) for row in memories]
    renderable = [d for d in decisions if d.renderable and d.display_text]
    blocked = [d for d in decisions if not d.renderable]
    lines = [f"{display} 的群友印象："]
    if aliases:
        lines.append("- 称呼：" + "、".join(list(dict.fromkeys(aliases))[:6]))
    if renderable:
        seen: set[str] = set()
        for d in sorted(renderable, key=lambda x: -x.priority):
            if d.display_text in seen:
                continue
            seen.add(d.display_text)
            lines.append(f"- {d.display_text}")
    else:
        lines.append("- 暂时没有可展示的稳定画像。")
    if include_policy_counts and blocked:
        reason_counts: dict[str, int] = {}
        for d in blocked:
            for r in d.reasons or ("blocked",):
                reason_counts[r] = reason_counts.get(r, 0) + 1
        summary = "，".join(f"{k}:{v}" for k, v in sorted(reason_counts.items()))
        lines.append(f"- 另有 {len(blocked)} 条 active 记忆被治理策略拦截，未渲染。{summary}")
    return "\n".join(lines)


def _term_match(row: dict[str, Any], terms: Iterable[str]) -> bool:
    keys = [_normalize_key(t) for t in terms if _normalize_key(t)]
    if not keys:
        return False
    hay = _normalize_key(" ".join(str(row.get(k) or "") for k in ("memory_text", "raw_evidence", "value", "predicate", "tags_json")))
    return any(k in hay for k in keys)


def soft_delete_memories(
    store: Any,
    user_id: str,
    *,
    terms: Iterable[str] = (),
    actor_user_id: str = "",
    reason: str = "admin_memory_delete",
    dry_run: bool = False,
) -> dict[str, Any]:
    uid = str(user_id or "").strip()
    if not uid:
        return {"matched": 0, "updated": 0, "memory_ids": []}
    store.initialize()
    terms_list = [str(t).strip() for t in terms if str(t).strip()]
    with store.connect() as conn:
        ensure_governance_audit_table(conn)
        rows = _fetch_active_memories(conn, uid)
        matched = [row for row in rows if _term_match(row, terms_list)] if terms_list else []
        ids = [str(r.get("id") or r.get("memory_id") or "") for r in matched if str(r.get("id") or r.get("memory_id") or "")]
        if dry_run or not ids:
            return {"matched": len(matched), "updated": 0, "memory_ids": ids}
        now = utc_now()
        for mid in ids:
            old = conn.execute("SELECT is_active FROM social_memories WHERE id=?", (mid,)).fetchone()
            conn.execute("UPDATE social_memories SET is_active=0, updated_at=? WHERE id=?", (now, mid))
            conn.execute(
                """
                INSERT INTO social_memory_governance_audit(id, action, memory_id, subject_user_id, actor_user_id, reason, old_is_active, new_is_active, created_at)
                VALUES (?, 'soft_delete', ?, ?, ?, ?, ?, 0, ?)
                """,
                (f"audit_{uuid.uuid4().hex}", mid, uid, str(actor_user_id or ""), reason, int(old[0]) if old else 1, now),
            )
        return {"matched": len(matched), "updated": len(ids), "memory_ids": ids}


def quarantine_policy_violations(store: Any, user_id: str, *, actor_user_id: str = "", dry_run: bool = False) -> dict[str, Any]:
    uid = str(user_id or "").strip()
    if not uid:
        return {"matched": 0, "updated": 0, "memory_ids": []}
    store.initialize()
    with store.connect() as conn:
        ensure_governance_audit_table(conn)
        rows = _fetch_active_memories(conn, uid)
        decisions = {d.memory_id: d for d in (classify_memory_row(row) for row in rows) if d.quarantine and d.memory_id}
        ids = list(decisions.keys())
        if dry_run or not ids:
            return {"matched": len(ids), "updated": 0, "memory_ids": ids, "reasons": {mid: decisions[mid].reasons for mid in ids}}
        now = utc_now()
        for mid in ids:
            old = conn.execute("SELECT is_active FROM social_memories WHERE id=?", (mid,)).fetchone()
            conn.execute("UPDATE social_memories SET is_active=0, updated_at=? WHERE id=?", (now, mid))
            conn.execute(
                """
                INSERT INTO social_memory_governance_audit(id, action, memory_id, subject_user_id, actor_user_id, reason, old_is_active, new_is_active, created_at)
                VALUES (?, 'quarantine', ?, ?, ?, ?, ?, 0, ?)
                """,
                (f"audit_{uuid.uuid4().hex}", mid, uid, str(actor_user_id or ""), ",".join(decisions[mid].reasons), int(old[0]) if old else 1, now),
            )
        return {"matched": len(ids), "updated": len(ids), "memory_ids": ids, "reasons": {mid: decisions[mid].reasons for mid in ids}}
