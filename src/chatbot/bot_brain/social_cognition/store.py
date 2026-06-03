from __future__ import annotations

import json
import logging
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.chatbot.bot_brain.models import Observation

from .extractor import (
    SocialMemoryCandidate,
    extract_social_memories,
    get_mentioned_display_names,
    get_mentioned_user_ids,
    get_scope_id,
    get_sender_display_name,
    get_sender_id,
)
from .memory_gate import MemoryGateDecision, memory_gate
from .memory_gate import CandidateMemory as CandidateMemory
from .policy import contains_offensive_judgement, contains_sensitive_private_info, is_safe_alias, normalize_alias
from .resolver import SocialResolver, load_aliases, normalize_reference
from .summarizer import summarize_profile

logger = logging.getLogger(__name__)
DEFAULT_SOCIAL_COGNITION_PATH = Path("data/social_cognition.sqlite")

DDL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS social_users (
    user_id TEXT PRIMARY KEY,
    display_name TEXT,
    aliases_json TEXT,
    first_seen_at TEXT,
    last_seen_at TEXT,
    profile_summary TEXT,
    profile_updated_at TEXT
);

CREATE TABLE IF NOT EXISTS social_memories (
    id TEXT PRIMARY KEY,
    subject_user_id TEXT,
    source_user_id TEXT,
    scope_id TEXT,
    source_type TEXT,
    memory_text TEXT,
    raw_evidence TEXT,
    confidence REAL,
    priority REAL,
    emotion_valence REAL,
    tags_json TEXT,
    created_at TEXT,
    updated_at TEXT,
    decay REAL,
    is_active INTEGER
);

CREATE INDEX IF NOT EXISTS idx_social_memories_subject ON social_memories(subject_user_id, is_active);
CREATE INDEX IF NOT EXISTS idx_social_memories_scope ON social_memories(scope_id, updated_at);

CREATE TABLE IF NOT EXISTS social_interactions (
    id TEXT PRIMARY KEY,
    scope_id TEXT,
    sender_user_id TEXT,
    mentioned_user_ids_json TEXT,
    message_text TEXT,
    created_at TEXT,
    importance REAL
);

CREATE INDEX IF NOT EXISTS idx_social_interactions_sender ON social_interactions(sender_user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_social_interactions_scope ON social_interactions(scope_id, created_at);


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


def _clip(text: str, limit: int) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    return clean[:limit]


def _alias_from_memory_text(text: str) -> str:
    match = re.search(r"“([^”]{1,24})”", str(text or ""))
    if not match:
        return ""
    alias = normalize_alias(match.group(1))
    return alias if is_safe_alias(alias) else ""

PROFILE_QUERY_SUFFIX_RE = re.compile(
    r"(是谁|是怎样的人|怎么样|怎样的人|什么样的人|什么样|你记得|记得|评价|印象|说说|描述|账号ID|qq号|user[_-]?id|uid|多少|多少号|号码|账号|帐号|，|,|。|？|\?|！|!)",
    re.I,
)


def _extract_reference_terms(text: str) -> list[str]:
    clean = re.sub(r"\[CQ:[^\]]+\]", " ", str(text or ""))
    clean = re.sub(r"@\d{5,12}", " ", clean)
    clean = re.sub(r"\s+", "", clean)
    if not clean:
        return []
    parts = [p for p in re.split(PROFILE_QUERY_SUFFIX_RE, clean) if p and not PROFILE_QUERY_SUFFIX_RE.fullmatch(p)]
    refs: list[str] = []
    for part in parts:
        candidate = part.strip("的他她它这个人这个群友")
        if 1 <= len(candidate) <= 24 and not re.fullmatch(r"\d+", candidate):
            refs.append(candidate)
    if not refs and 1 <= len(clean) <= 24:
        refs.append(clean)
    return list(dict.fromkeys(refs))[:5]


class SocialCognitionStore:
    def __init__(self, path: str | Path = DEFAULT_SOCIAL_COGNITION_PATH) -> None:
        self.path = Path(path)
        self._initialized = False
        self.resolver = SocialResolver(self.connect)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        if self._initialized:
            return
        try:
            with self.connect() as conn:
                conn.executescript(DDL)
                conn.commit()
            self._initialized = True
        except sqlite3.Error:
            logger.exception("Failed to initialize social cognition database")
            raise

    def upsert_user(self, user_id: str, *, display_name: str = "", aliases: Iterable[str] = ()) -> None:
        self.initialize()
        uid = str(user_id or "").strip()
        if not uid:
            return
        now = utc_now()
        alias_set = {str(a).strip() for a in aliases if str(a).strip()}
        if display_name.strip():
            alias_set.add(display_name.strip())
        try:
            with self.connect() as conn:
                row = conn.execute("SELECT display_name, aliases_json FROM social_users WHERE user_id=?", (uid,)).fetchone()
                if row:
                    existing = set(load_aliases(row["aliases_json"]))
                    aliases_json = _json_dumps(sorted((existing | alias_set) - {uid}))
                    final_name = display_name.strip() or row["display_name"] or ""
                    conn.execute(
                        "UPDATE social_users SET display_name=?, aliases_json=?, last_seen_at=? WHERE user_id=?",
                        (final_name, aliases_json, now, uid),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO social_users(user_id, display_name, aliases_json, first_seen_at, last_seen_at, profile_summary, profile_updated_at)
                        VALUES (?, ?, ?, ?, ?, '', '')
                        """,
                        (uid, display_name.strip(), _json_dumps(sorted(alias_set - {uid})), now, now),
                    )
        except sqlite3.Error:
            logger.exception("Failed to upsert social user user_id=%s", uid)

    def add_memory(self, candidate: SocialMemoryCandidate) -> str | None:
        return self.add_memory_event(candidate)

    def add_memory_event(self, candidate: SocialMemoryCandidate) -> str | None:
        decision = memory_gate.evaluate(candidate)
        if not decision.accepted:
            logger.debug("Rejected social memory candidate reason=%s flags=%s", decision.reason, decision.risk_flags)
            return None
        return self._add_accepted_memory_event(candidate, decision)

    def _add_accepted_memory_event(self, candidate: SocialMemoryCandidate, decision: MemoryGateDecision) -> str | None:
        self.initialize()
        memory_text = decision.normalized_memory_text or ""
        if not memory_text or contains_sensitive_private_info(candidate.value):
            return None
        confidence = max(0.0, min(1.0, float(candidate.confidence)))
        priority = max(0.0, min(1.0, float(candidate.priority)))
        tags = list(dict.fromkeys(candidate.tags or []))
        if candidate.source_type == "admin_said":
            confidence = max(confidence, 0.88)
            priority = max(priority, 0.80)
            if "admin_confirmed" not in tags:
                tags.append("admin_confirmed")
        elif candidate.source_type == "self_said":
            confidence = max(confidence, 0.78)
        elif candidate.source_type == "other_said":
            confidence = min(max(confidence, 0.35), 0.55)
            if "unverified_other_claim" not in tags:
                tags.append("unverified_other_claim")
        if contains_offensive_judgement(memory_text):
            confidence = min(confidence, 0.25)
            priority = min(priority, 0.25)
        now = utc_now()
        mid = f"smem_{uuid.uuid4().hex}"
        try:
            with self.connect() as conn:
                existing = conn.execute(
                    """
                    SELECT id, confidence, priority, tags_json
                    FROM social_memories
                    WHERE subject_user_id=? AND scope_id=? AND source_type=? AND memory_text=? AND is_active=1
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    (str(candidate.subject_user_id), str(candidate.scope_id), str(candidate.source_type), _clip(memory_text, 500)),
                ).fetchone()
                if existing:
                    merged_tags = sorted(set(_json_loads(existing["tags_json"], [])) | set(tags))
                    conn.execute(
                        """
                        UPDATE social_memories
                        SET confidence=?, priority=?, raw_evidence=?, tags_json=?, updated_at=?, decay=1.0
                        WHERE id=?
                        """,
                        (
                            max(float(existing["confidence"] or 0.0), confidence),
                            max(float(existing["priority"] or 0.0), priority),
                            _clip(candidate.raw_evidence, 700),
                            _json_dumps(merged_tags),
                            now,
                            existing["id"],
                        ),
                    )
                    self._apply_alias_candidate(conn, candidate, memory_text, merged_tags)
                    return str(existing["id"])
                conn.execute(
                    """
                    INSERT INTO social_memories(
                        id, subject_user_id, source_user_id, scope_id, source_type, memory_text, raw_evidence,
                        confidence, priority, emotion_valence, tags_json, created_at, updated_at, decay, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        mid,
                        str(candidate.subject_user_id),
                        str(candidate.source_user_id),
                        str(candidate.scope_id),
                        str(candidate.source_type),
                        _clip(memory_text, 500),
                        _clip(candidate.raw_evidence, 700),
                        confidence,
                        priority,
                        float(candidate.emotion_valence),
                        _json_dumps(tags),
                        now,
                        now,
                        1.0,
                    ),
                )
                self._apply_alias_candidate(conn, candidate, memory_text, tags)
            return mid
        except sqlite3.Error:
            logger.exception("Failed to add social memory subject=%s source=%s", candidate.subject_user_id, candidate.source_user_id)
            return None

    def _apply_alias_candidate(self, conn: sqlite3.Connection, candidate: SocialMemoryCandidate, memory_text: str | None = None, tags: list[str] | None = None) -> None:
        tag_set = set(tags or candidate.tags or [])
        if "alias" not in tag_set and "nickname" not in tag_set:
            return
        alias = _alias_from_memory_text(memory_text or candidate.memory_text)
        if not alias:
            return
        subject_id = str(candidate.subject_user_id or "").strip()
        if not subject_id:
            return
        try:
            row = conn.execute("SELECT display_name, aliases_json FROM social_users WHERE user_id=?", (subject_id,)).fetchone()
            aliases = set(load_aliases(row["aliases_json"])) if row else set()
            aliases.add(alias)
            display_name = str(row["display_name"] or "") if row else ""
            final_display = display_name or alias
            now = utc_now()
            if row:
                conn.execute(
                    "UPDATE social_users SET display_name=?, aliases_json=?, last_seen_at=? WHERE user_id=?",
                    (final_display, _json_dumps(sorted(aliases - {subject_id})), now, subject_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO social_users(user_id, display_name, aliases_json, first_seen_at, last_seen_at, profile_summary, profile_updated_at)
                    VALUES (?, ?, ?, ?, ?, '', '')
                    """,
                    (subject_id, final_display, _json_dumps(sorted(aliases - {subject_id})), now, now),
                )
        except sqlite3.Error:
            logger.exception("Failed to apply alias candidate subject=%s alias=%s", subject_id, alias)

    def record_interaction(self, observation: Observation) -> None:
        self.initialize()
        text = _clip(getattr(observation, "raw_message_text", "") or getattr(observation, "text", ""), 900)
        if not text:
            return
        sender_id = get_sender_id(observation)
        if not sender_id:
            return
        mentioned = get_mentioned_user_ids(observation)
        importance = self._importance(text)
        try:
            with self.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO social_interactions(id, scope_id, sender_user_id, mentioned_user_ids_json, message_text, created_at, importance)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"sint_{uuid.uuid4().hex}",
                        get_scope_id(observation),
                        sender_id,
                        _json_dumps(mentioned),
                        text,
                        utc_now(),
                        importance,
                    ),
                )
        except sqlite3.Error:
            logger.exception("Failed to record social interaction sender=%s", sender_id)

    def record_observation(self, observation: Observation) -> list[str]:
        text = str(getattr(observation, "text", "") or "").strip()
        if not text or text.lstrip().startswith(("/", "!", "！")):
            return []
        sender_id = get_sender_id(observation)
        if not sender_id:
            return []
        self.upsert_user(sender_id, display_name=get_sender_display_name(observation))
        mentioned_names = get_mentioned_display_names(observation)
        for uid in get_mentioned_user_ids(observation):
            self.upsert_user(uid, display_name=mentioned_names.get(uid, ""))
        self.record_interaction(observation)
        written: list[str] = []
        for candidate in extract_social_memories(observation, resolver=self.resolver):
            decision = memory_gate.evaluate(candidate)
            if not decision.accepted:
                logger.debug("Rejected social memory candidate reason=%s flags=%s", decision.reason, decision.risk_flags)
                continue
            mid = self._add_accepted_memory_event(candidate, decision)
            if mid:
                written.append(mid)
        return written

    def observe_and_get_context(self, observation: Observation) -> str:
        self.record_observation(observation)
        return self.render_context_for_observation(observation)

    def memories_for_user(self, user_id: str, *, query: str = "", scope_id: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
        self.initialize()
        uid = str(user_id or "").strip()
        if not uid:
            return []
        try:
            with self.connect() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM social_memories
                    WHERE subject_user_id=? AND is_active=1 AND confidence>=0.2
                    ORDER BY (priority * 0.45 + confidence * 0.45 + decay * 0.10) DESC, updated_at DESC
                    LIMIT ?
                    """,
                    (uid, limit),
                ).fetchall()
        except sqlite3.Error:
            logger.exception("Failed to retrieve social memories user_id=%s", uid)
            return []
        memories = [dict(row) for row in rows]
        for memory in memories:
            memory["tags"] = _json_loads(memory.get("tags_json"), [])
        return memories

    def candidate_user_ids_from_text(self, text: str, *, scope_id: str | None = None) -> list[str]:
        """Resolve user references from free-form text.

        This supports the real chat case:
        - A was mentioned and described as "网管" earlier.
        - Later the user asks "网管是谁，账号ID多少" without @-mentioning A.

        The resolver first checks stable user aliases/display names, then falls back to
        active memory evidence. It does not special-case a concrete alias such as "网管";
        it extracts short target references from identity/profile questions and matches
        them against memory text for the subject user.
        """
        self.initialize()
        raw_text = str(text or "")
        normalized = normalize_reference(raw_text)
        if not normalized:
            return []

        refs = _extract_reference_terms(raw_text)
        ref_norms = [normalize_reference(ref) for ref in refs if normalize_reference(ref)]
        found: list[str] = []
        try:
            with self.connect() as conn:
                user_rows = conn.execute("SELECT user_id, display_name, aliases_json FROM social_users").fetchall()
                memory_rows = conn.execute(
                    """
                    SELECT subject_user_id, memory_text, tags_json
                    FROM social_memories
                    WHERE is_active=1 AND confidence>=0.2
                    ORDER BY updated_at DESC
                    LIMIT 500
                    """
                ).fetchall()
        except sqlite3.Error:
            logger.exception("Failed to scan social cognition references for text")
            return []

        for row in user_rows:
            aliases = [row["display_name"], *load_aliases(row["aliases_json"])]
            for alias in aliases:
                alias_norm = normalize_reference(alias)
                if alias_norm and len(alias_norm) >= 2 and (alias_norm in normalized or normalized in alias_norm):
                    found.append(str(row["user_id"]))
                    break

        # Memory-evidence fallback: map short terms like "网管" to the subject whose
        # active memories mention that term. This is deliberately conservative: it only
        # uses extracted query references, not every token in the sentence.
        for row in memory_rows:
            memory_norm = normalize_reference(row["memory_text"])
            if not memory_norm:
                continue
            for ref_norm in ref_norms:
                if len(ref_norm) >= 2 and ref_norm in memory_norm:
                    found.append(str(row["subject_user_id"]))
                    break
        return list(dict.fromkeys(found))[:5]

    def resolve_user_reference(self, reference: str, *, scope_id: str | None = None) -> str | None:
        self.initialize()
        return self.resolver.resolve(reference, scope_id=scope_id)

    def render_context_for_observation(self, observation: Observation) -> str:
        from .retriever import SocialRetriever

        result = SocialRetriever(self).retrieve_for_observation(observation)
        return result.context

    def recent_events(self, reference: str | None = None, *, limit: int = 5) -> list[dict[str, Any]]:
        self.initialize()
        user_id = self.resolve_user_reference(reference) if reference else None
        try:
            with self.connect() as conn:
                if user_id:
                    rows = conn.execute(
                        """
                        SELECT * FROM social_interactions
                        WHERE sender_user_id=? OR mentioned_user_ids_json LIKE ?
                        ORDER BY created_at DESC
                        LIMIT ?
                        """,
                        (user_id, f'%"{user_id}"%', limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM social_interactions ORDER BY created_at DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
        except sqlite3.Error:
            logger.exception("Failed to load social interaction events")
            return []
        return [dict(row) for row in rows]

    def profile_summary(self, user_id: str, *, scope_id: str | None = None, limit: int = 5) -> str:
        self.initialize()
        uid = str(user_id or "").strip()
        if not uid:
            return ""
        try:
            with self.connect() as conn:
                user = conn.execute("SELECT display_name FROM social_users WHERE user_id=?", (uid,)).fetchone()
        except sqlite3.Error:
            logger.exception("Failed to load social user summary user_id=%s", uid)
            return ""
        memories = self.memories_for_user(uid, scope_id=scope_id, limit=limit)
        if not user and not memories:
            return ""
        display = str(user["display_name"] or "") if user else ""
        return summarize_profile(display, memories)

    def stats(self) -> dict[str, int]:
        self.initialize()
        try:
            with self.connect() as conn:
                return {
                    "users": int(conn.execute("SELECT COUNT(*) FROM social_users").fetchone()[0]),
                    "memories": int(conn.execute("SELECT COUNT(*) FROM social_memories WHERE is_active=1").fetchone()[0]),
                    "interactions": int(conn.execute("SELECT COUNT(*) FROM social_interactions").fetchone()[0]),
                }
        except sqlite3.Error:
            logger.exception("Failed to get social cognition stats")
            return {"users": 0, "memories": 0, "interactions": 0}

    def forget_user(self, reference: str) -> bool:
        self.initialize()
        uid = self.resolve_user_reference(reference) or (str(reference).strip() if re.fullmatch(r"\d{5,12}", str(reference).strip()) else "")
        if not uid:
            return False
        try:
            with self.connect() as conn:
                conn.execute("DELETE FROM social_users WHERE user_id=?", (uid,))
                conn.execute("UPDATE social_memories SET is_active=0, updated_at=? WHERE subject_user_id=? OR source_user_id=?", (utc_now(), uid, uid))
                conn.execute("DELETE FROM social_interactions WHERE sender_user_id=?", (uid,))
            return True
        except sqlite3.Error:
            logger.exception("Failed to forget social user user_id=%s", uid)
            return False

    def _importance(self, text: str) -> float:
        score = 0.25
        if re.search(r"(喜欢|擅长|会|经常|平时|记住|记得|印象|是谁|怎么样|怎样的人)", text):
            score += 0.3
        if len(text) > 80:
            score += 0.08
        if contains_offensive_judgement(text):
            score -= 0.1
        return max(0.05, min(0.9, score))


social_cognition_store = SocialCognitionStore()
