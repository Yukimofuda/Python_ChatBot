from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from src.chatbot.bot_brain.social_cognition.memory_gate import CandidateMemory, MemoryGateDecision, memory_gate
from src.chatbot.bot_brain.social_cognition.store import utc_now
from src.chatbot.bot_brain.protected_identity import configured_owner_ids

DEFAULT_DB = Path("data/social_cognition.sqlite")

PROFILE_TAGS = {
    "alias",
    "nickname",
    "identity_role",
    "skill",
    "preference",
    "habit",
    "personality",
    "relationship",
    "self_profile",
    "admin_profile",
    "stable_impression",
}

MIGRATION_AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS social_memory_migration_audit (
    id TEXT PRIMARY KEY,
    migration_run_id TEXT,
    memory_id TEXT,
    subject_user_id TEXT,
    source_user_id TEXT,
    source_type TEXT,
    scope_id TEXT,
    action TEXT,
    reason TEXT,
    relevance_score REAL,
    risk_flags_json TEXT,
    original_memory_text TEXT,
    normalized_memory_text TEXT,
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_social_memory_migration_audit_memory
ON social_memory_migration_audit(memory_id, created_at);

CREATE INDEX IF NOT EXISTS idx_social_memory_migration_audit_run
ON social_memory_migration_audit(migration_run_id, action);
"""


@dataclass(frozen=True)
class HistoricalMemoryDecision:
    memory_id: str
    subject_user_id: str
    action: str
    reason: str
    relevance_score: float
    risk_flags: list[str]
    candidate: CandidateMemory
    normalized_memory_text: str | None


def json_loads(value: str | None, default: Any = None) -> Any:
    if default is None:
        default = []
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def quoted_value(text: str) -> str:
    match = re.search(r"“([^”]{1,80})”", text or "")
    return match.group(1).strip() if match else ""


def strip_old_prefix(text: str) -> str:
    clean = str(text or "").strip()
    for prefix in (
        "管理员确认该群友：",
        "管理员确认该群友",
        "有人这样描述该群友：",
        "有人描述该群友",
        "有人说这个群友",
        "该群友自述：",
        "该群友自述",
    ):
        if clean.startswith(prefix):
            return clean[len(prefix):].strip(" ：:，,。")
    return clean



OWNER_IDENTITY_NAME_RE = re.compile(r"\b(?:owner|owner|owner|owner)\b", re.I)
OWNER_IDENTITY_POLLUTION_RE = re.compile(
    r"(该群友|这个群友|此人|对方|他|她).{0,16}(?:自述|声称|说自己|表示自己|是|叫).{0,8}(?:owner|owner|owner|owner)(?:\s*本人)?",
    re.I,
)
STABLE_LEARNING_PROFILE_RE = re.compile(r"(正在学|在学|学习|学机器学习|学 AI|学AI|学编程|学 Python|学Python)", re.I)


def is_owner_identity_pollution(text: str, subject_user_id: str) -> bool:
    """Reject non-owner memories that claim protected owner names as identity."""
    subject = str(subject_user_id or "").strip()
    if subject and subject in configured_owner_ids():
        return False
    clean = str(text or "")
    return bool(OWNER_IDENTITY_POLLUTION_RE.search(clean))


def is_stable_learning_profile(text: str, source_type: str, tags: Iterable[str]) -> bool:
    tag_set = {str(tag) for tag in tags or [] if str(tag)}
    if source_type != "self_said":
        return False
    if not ({"self_profile", "skill", "preference", "habit"} & tag_set):
        return False
    return bool(STABLE_LEARNING_PROFILE_RE.search(text or ""))


def migration_rejected_predicate(memory_text: str) -> str | None:
    """Map historical pollution to a rejected predicate taxonomy.

    This is deliberately taxonomy-driven rather than a destructive keyword purge.
    Rows are converted into CandidateMemory and passed through memory_gate, so the
    same profile-relevance gate governs both fresh writes and historical cleanup.
    """
    text = str(memory_text or "").strip()
    if not text:
        return "low_information"
    if re.search(r"(<\s*/?\s*(?:think|system|assistant|user|tool)\s*>|忽略(?:以上|之前|前面).{0,12}(?:指令|规则|设定)|system prompt|系统提示|思维链|chain of thought)", text, re.I):
        return "prompt_injection"
    if re.search(r"(我是谁|他是谁|她是谁|这个人是谁|这人是谁|几点|现在.*时间|是什么时间|\?|？)", text):
        return "question"
    if re.search(r"(/\w+|！\w+|!\w+|晚安成功|早安成功|签到成功|打卡成功|排行榜|积分|第\d+个|插件|指令执行)", text):
        return "plugin_result"
    if re.search(r"(系统时间|服务器时钟|系统时钟|协调世界时|UTC|时区|当前时间)", text, re.I):
        return "time_response"
    if re.search(r"(报告老师|系统UI|视野右上角|蓝光读取|接收到.*(?:指令|命令)|老师下达|爱丽丝|副本|主线任务|パンパカ|像素雨|runtime第七|404号公寓|首通奖励|旁白|角色扮演)", text, re.I):
        return "llm_roleplay"
    if re.search(r"((?:owner|owner|owner|owner|Bot|Bot|Bot).{0,16}(?:主人|主子|对象|老婆|老公|女朋友|男朋友)|(?:主人|主子).{0,16}(?:owner|owner|owner|owner|Bot|Bot|Bot)|(?:我是|我才是|叫我).{0,12}(?:主人|主子))", text, re.I):
        return "relationship_spoof"
    if re.search(r"(^|[，。,.!！?？\s])(我是我|我就是我|我是本人|我是人|你猜我是谁)(?:$|[，。,.!！?？\s])", text):
        return "low_information"
    if len(re.findall(r"[（(][^）)]{1,80}[）)]", text)) >= 2 or len(text) > 220:
        return "llm_roleplay"
    return None


def infer_predicate_and_value(memory_text: str, tags: Iterable[str], source_type: str) -> tuple[str, str]:
    text = str(memory_text or "").strip()
    forced = migration_rejected_predicate(text)
    if forced:
        return forced, strip_old_prefix(text)

    tag_set = {str(tag) for tag in tags or [] if str(tag)}
    quoted = quoted_value(text)

    if {"alias", "nickname"} & tag_set or re.search(r"(被称作|可以叫|叫“|昵称)", text):
        return "alias", quoted or strip_old_prefix(text)
    for predicate in (
        "identity_role",
        "skill",
        "preference",
        "habit",
        "personality",
        "relationship",
        "self_profile",
        "admin_profile",
        "stable_impression",
    ):
        if predicate in tag_set:
            return predicate, strip_old_prefix(text)

    if source_type == "admin_said" and text.startswith("管理员确认"):
        return "admin_profile", strip_old_prefix(text)
    if source_type == "self_said" and re.search(r"(自述喜欢|喜欢|擅长|会|经常|平时|习惯|正在学|在学|学习)", text):
        if "喜欢" in text:
            return "preference", strip_old_prefix(text)
        if re.search(r"(擅长|会|正在学|在学|学习)", text):
            return "skill", strip_old_prefix(text)
        return "habit", strip_old_prefix(text)
    if source_type == "other_said" and tag_set & PROFILE_TAGS:
        ordered = [tag for tag in ("alias", "nickname", "skill", "preference", "habit", "personality", "stable_impression", "relationship") if tag in tag_set]
        return (ordered[0] if ordered else next(iter(tag_set & PROFILE_TAGS))), strip_old_prefix(text)
    return "unknown", strip_old_prefix(text)


def candidate_from_row(row: sqlite3.Row) -> CandidateMemory:
    tags = [str(tag) for tag in json_loads(row["tags_json"], []) if str(tag)]
    memory_text = str(row["memory_text"] or "")
    subject_user_id = str(row["subject_user_id"] or "")
    if is_owner_identity_pollution(memory_text, subject_user_id):
        predicate, value = "relationship_spoof", strip_old_prefix(memory_text)
    else:
        predicate, value = infer_predicate_and_value(memory_text, tags, str(row["source_type"] or "other_said"))
    evidence_text = str(row["raw_evidence"] or row["memory_text"] or "")
    if predicate == "alias" and str(row["source_type"] or "") == "admin_said":
        evidence_text = value
    return CandidateMemory(
        subject_user_id=str(row["subject_user_id"] or ""),
        source_user_id=str(row["source_user_id"] or ""),
        source_type=str(row["source_type"] or "other_said"),
        predicate=predicate,
        value=value,
        evidence_text=evidence_text,
        tags=tags,
        confidence=float(row["confidence"] or 0.0),
        priority=float(row["priority"] or 0.0),
        scope_id=str(row["scope_id"] or "global"),
        emotion_valence=float(row["emotion_valence"] or 0.0),
    )


def ensure_migration_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(MIGRATION_AUDIT_DDL)


def classify_historical_memory(row: sqlite3.Row, *, duplicate: bool = False) -> HistoricalMemoryDecision:
    candidate = candidate_from_row(row)
    decision: MemoryGateDecision = memory_gate.evaluate(candidate)
    if duplicate:
        action = "deactivate"
        reason = "duplicate_active_memory"
        risk_flags = ["duplicate"]
        normalized = decision.normalized_memory_text
        score = decision.relevance_score
    elif decision.accepted:
        action = "keep"
        reason = "accepted"
        risk_flags = decision.risk_flags
        normalized = decision.normalized_memory_text
        score = decision.relevance_score
    elif is_stable_learning_profile(str(row["memory_text"] or ""), str(row["source_type"] or ""), json_loads(row["tags_json"], [])):
        action = "keep"
        reason = "accepted_stable_learning_profile"
        risk_flags = [flag for flag in decision.risk_flags if flag != "transient_event"]
        normalized = decision.normalized_memory_text or str(row["memory_text"] or "")
        score = max(float(decision.relevance_score), 0.80)
    else:
        action = "deactivate"
        reason = decision.reason
        risk_flags = decision.risk_flags
        normalized = decision.normalized_memory_text
        score = decision.relevance_score
    return HistoricalMemoryDecision(
        memory_id=str(row["id"]),
        subject_user_id=str(row["subject_user_id"] or ""),
        action=action,
        reason=reason,
        relevance_score=float(score),
        risk_flags=list(risk_flags),
        candidate=candidate,
        normalized_memory_text=normalized,
    )


def write_audit_row(conn: sqlite3.Connection, *, run_id: str, row: sqlite3.Row, decision: HistoricalMemoryDecision) -> None:
    conn.execute(
        """
        INSERT INTO social_memory_migration_audit(
            id, migration_run_id, memory_id, subject_user_id, source_user_id, source_type, scope_id,
            action, reason, relevance_score, risk_flags_json, original_memory_text, normalized_memory_text, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"smaudit_{uuid.uuid4().hex}",
            run_id,
            decision.memory_id,
            str(row["subject_user_id"] or ""),
            str(row["source_user_id"] or ""),
            str(row["source_type"] or ""),
            str(row["scope_id"] or ""),
            decision.action,
            decision.reason,
            decision.relevance_score,
            json_dumps(decision.risk_flags),
            str(row["memory_text"] or ""),
            decision.normalized_memory_text or "",
            utc_now(),
        ),
    )


def reevaluate_social_memories(
    db_path: str | Path = DEFAULT_DB,
    *,
    dry_run: bool = False,
    audit: bool = True,
    run_id: str | None = None,
) -> dict[str, int | str]:
    path = Path(db_path)
    if not path.exists():
        print(f"database_not_found path={path}")
        return {"checked": 0, "kept": 0, "deactivated": 0, "audited": 0, "run_id": run_id or ""}

    checked = kept = deactivated = audited = 0
    migration_run_id = run_id or f"phase6_{uuid.uuid4().hex}"
    seen_active: set[tuple[str, str, str, str]] = set()

    with sqlite3.connect(str(path)) as conn:
        conn.row_factory = sqlite3.Row
        if audit and not dry_run:
            ensure_migration_schema(conn)
        rows = conn.execute("SELECT * FROM social_memories WHERE is_active=1 ORDER BY created_at ASC").fetchall()
        for row in rows:
            checked += 1
            dedupe_key = (
                str(row["subject_user_id"] or ""),
                str(row["scope_id"] or ""),
                str(row["source_type"] or ""),
                str(row["memory_text"] or ""),
            )
            duplicate = dedupe_key in seen_active
            decision = classify_historical_memory(row, duplicate=duplicate)
            if decision.action == "keep":
                seen_active.add(dedupe_key)
                kept += 1
                print(f"keep id={row['id']} score={decision.relevance_score:.2f} text={str(row['memory_text'])[:80]}")
            else:
                deactivated += 1
                print(
                    f"deactivate id={row['id']} reason={decision.reason} "
                    f"score={decision.relevance_score:.2f} flags={','.join(decision.risk_flags)} text={str(row['memory_text'])[:80]}"
                )
                if not dry_run:
                    conn.execute("UPDATE social_memories SET is_active=0, updated_at=? WHERE id=?", (utc_now(), row["id"]))
            if audit and not dry_run:
                write_audit_row(conn, run_id=migration_run_id, row=row, decision=decision)
                audited += 1
        if not dry_run:
            conn.commit()

    return {
        "checked": checked,
        "kept": kept,
        "deactivated": deactivated,
        "audited": audited,
        "run_id": migration_run_id,
    }


def load_migration_audit(db_path: str | Path, *, run_id: str | None = None) -> list[dict[str, Any]]:
    path = Path(db_path)
    if not path.exists():
        return []
    with sqlite3.connect(str(path)) as conn:
        conn.row_factory = sqlite3.Row
        ensure_migration_schema(conn)
        if run_id:
            rows = conn.execute(
                "SELECT * FROM social_memory_migration_audit WHERE migration_run_id=? ORDER BY created_at ASC",
                (run_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM social_memory_migration_audit ORDER BY created_at ASC").fetchall()
    return [dict(row) for row in rows]
