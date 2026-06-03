from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Callable, Iterable, Any

from src.chatbot.bot_brain.models import Observation


def load_aliases(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        data = json.loads(value)
        if isinstance(data, list):
            return [str(item).strip() for item in data if str(item).strip()]
    except Exception:
        return []
    return []


def normalize_reference(value: str | None) -> str:
    text = str(value or "")
    text = re.sub(r"\[CQ:[^\]]+\]", " ", text)
    text = re.sub(r"@\s*", "", text)
    text = text.strip().strip("'\"“”‘’（）()[]【】<>《》.,，。！？?！:：;； ")
    text = re.sub(r"\s+", "", text)
    return text.lower()


@dataclass(frozen=True)
class ResolvedSubject:
    status: str  # ok / none / ambiguous
    user_id: str = ""
    display_name: str = ""
    matched_reference: str = ""
    reason: str = ""
    candidates: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.status == "ok" and bool(self.user_id)


PROFILE_QUERY_SUFFIX_RE = re.compile(
    r"(是谁|是怎样的人|怎么样|怎样的人|什么样的人|什么样|你记得|记得|评价|印象|说说|描述|账号ID|qq号|user[_-]?id|uid|多少|多少号|号码|账号|帐号|，|,|。|？|\?|！|!)",
    re.I,
)


def reference_terms_from_text(text: str) -> list[str]:
    clean = re.sub(r"\[CQ:[^\]]+\]", " ", str(text or ""))
    clean = re.sub(r"@\d{5,12}", " ", clean)
    clean = re.sub(r"\s+", "", clean)
    if not clean:
        return []
    parts = [p for p in re.split(PROFILE_QUERY_SUFFIX_RE, clean) if p and not PROFILE_QUERY_SUFFIX_RE.fullmatch(p)]
    refs: list[str] = []
    for part in parts:
        candidate = part.strip("的他她它这个人这个群友这人")
        if 1 <= len(candidate) <= 24 and not re.fullmatch(r"\d+", candidate):
            refs.append(candidate)
    if not refs and 1 <= len(clean) <= 24:
        refs.append(clean)
    return list(dict.fromkeys(refs))[:5]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


class SocialResolver:
    """Resolve mutable user references to platform user_id.

    Phase 2 boundary: this module owns reference resolution. LLM output, aliases,
    display names and mentions are only clues; platform user_id remains the identity key.
    """

    def __init__(self, connect_factory: Callable[[], sqlite3.Connection]):
        self._connect_factory = connect_factory

    def resolve(self, reference: str, *, scope_id: str | None = None) -> str | None:
        result = self.resolve_ref(reference, scope_id=scope_id)
        return result.user_id if result.ok else None

    def resolve_ref(self, reference: str, *, scope_id: str | None = None) -> ResolvedSubject:
        ref = str(reference or "").strip()
        ref_norm = normalize_reference(ref)
        if not ref_norm:
            return ResolvedSubject("none", reason="empty_reference")
        try:
            with self._connect_factory() as conn:
                if not _table_exists(conn, "social_users"):
                    return ResolvedSubject("none", reason="missing_social_users")
                direct = self._resolve_direct_user_id(conn, ref)
                if direct.ok:
                    return direct
                matches = self._match_user_rows(conn, ref_norm)
                matches.update(self._match_active_memory_aliases(conn, ref_norm))
        except sqlite3.Error:
            return ResolvedSubject("none", reason="sqlite_error")
        if len(matches) == 1:
            uid, payload = next(iter(matches.items()))
            return ResolvedSubject("ok", uid, payload.get("display_name", ""), payload.get("matched", ref), payload.get("reason", "alias_or_display_name"))
        if len(matches) > 1:
            return ResolvedSubject("ambiguous", reason="multiple_reference_matches", candidates=tuple(sorted(matches)))
        return ResolvedSubject("none", reason="no_match")

    def candidate_user_ids_from_text(self, text: str, *, scope_id: str | None = None) -> list[str]:
        found: list[str] = []
        for term in reference_terms_from_text(text):
            result = self.resolve_ref(term, scope_id=scope_id)
            if result.ok and result.user_id not in found:
                found.append(result.user_id)
        return found[:5]

    def resolve_unique_non_bot_mention(self, observation: Observation) -> ResolvedSubject:
        mentioned = _mentioned_user_ids(observation)
        bot_ids = _bot_ids(observation)
        sender_id = _sender_id(observation)
        targets: list[str] = []
        for uid in mentioned:
            sid = str(uid)
            if sid and sid not in bot_ids and sid != sender_id and sid not in targets:
                targets.append(sid)
        if len(targets) == 1:
            return self._subject_from_user_id(targets[0], reason="unique_non_bot_mention")
        if len(targets) > 1:
            return ResolvedSubject("ambiguous", reason="multiple_non_bot_mentions", candidates=tuple(targets))
        return ResolvedSubject("none", reason="no_non_bot_mention")

    def _subject_from_user_id(self, user_id: str, *, reason: str) -> ResolvedSubject:
        uid = str(user_id or "").strip()
        if not uid:
            return ResolvedSubject("none", reason="empty_user_id")
        display = ""
        try:
            with self._connect_factory() as conn:
                if _table_exists(conn, "social_users"):
                    row = conn.execute("SELECT display_name FROM social_users WHERE user_id=?", (uid,)).fetchone()
                    if row:
                        display = str(row["display_name"] or "")
        except Exception:
            pass
        return ResolvedSubject("ok", uid, display, uid, reason)

    def _resolve_direct_user_id(self, conn: sqlite3.Connection, reference: str) -> ResolvedSubject:
        ref = str(reference or "").strip()
        if not re.fullmatch(r"\d{5,12}", ref):
            return ResolvedSubject("none", reason="not_user_id")
        row = conn.execute("SELECT user_id, display_name FROM social_users WHERE user_id=?", (ref,)).fetchone()
        if row:
            return ResolvedSubject("ok", str(row["user_id"]), str(row["display_name"] or ""), ref, "direct_user_id")
        return ResolvedSubject("ok", ref, "", ref, "direct_user_id_unseen")

    def _match_user_rows(self, conn: sqlite3.Connection, ref_norm: str) -> dict[str, dict[str, str]]:
        matches: dict[str, dict[str, str]] = {}
        for row in conn.execute("SELECT user_id, display_name, aliases_json FROM social_users").fetchall():
            uid = str(row["user_id"])
            display = str(row["display_name"] or "")
            aliases = [display, *load_aliases(row["aliases_json"])]
            for alias in aliases:
                alias_norm = normalize_reference(alias)
                if alias_norm and (alias_norm == ref_norm or (len(ref_norm) >= 2 and ref_norm in alias_norm) or (len(alias_norm) >= 2 and alias_norm in ref_norm)):
                    matches[uid] = {"display_name": display, "matched": str(alias), "reason": "display_name_or_alias"}
                    break
        return matches

    def _match_active_memory_aliases(self, conn: sqlite3.Connection, ref_norm: str) -> dict[str, dict[str, str]]:
        matches: dict[str, dict[str, str]] = {}
        if not _table_exists(conn, "social_memories"):
            return matches
        rows = conn.execute(
            """
            SELECT subject_user_id, memory_text, tags_json
            FROM social_memories
            WHERE is_active=1 AND confidence>=0.2
            ORDER BY updated_at DESC
            LIMIT 500
            """
        ).fetchall()
        for row in rows:
            memory_norm = normalize_reference(row["memory_text"])
            if ref_norm and len(ref_norm) >= 2 and ref_norm in memory_norm:
                uid = str(row["subject_user_id"])
                matches[uid] = {"display_name": "", "matched": ref_norm, "reason": "active_memory_alias"}
        return matches


def _features(observation: Observation) -> dict[str, Any]:
    return getattr(observation, "features", {}) or {}


def _mentioned_user_ids(observation: Observation) -> list[str]:
    direct = getattr(observation, "mentioned_user_ids", None) or []
    if direct:
        return [str(x) for x in direct if str(x)]
    raw = _features(observation).get("mentioned_user_ids") or []
    return [str(x) for x in raw if str(x)] if isinstance(raw, list) else []


def _bot_ids(observation: Observation) -> set[str]:
    ids: set[str] = set()
    for key in ("bot_id", "self_id", "bot_self_id"):
        value = _features(observation).get(key)
        if value:
            ids.add(str(value))
    direct_bot = getattr(observation, "bot_id", "") or ""
    if direct_bot:
        ids.add(str(direct_bot))
    return {x for x in ids if x}


def _sender_id(observation: Observation) -> str:
    return str(getattr(observation, "sender_id", None) or getattr(observation, "user_id", "") or "")
