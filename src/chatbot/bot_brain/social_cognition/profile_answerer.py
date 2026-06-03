from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Iterable

from src.chatbot.bot_brain.memory_decision_frame import (
    SYSTEM_TRACE_RE,
    MemoryDecisionFrame,
    build_memory_decision_frame,
)
from src.chatbot.bot_brain.models import Observation
from src.chatbot.bot_brain.social_cognition.alias_name_index import (
    AliasNameCandidate,
    inspect_alias as inspect_alias_name,
    is_label_like,
    search_alias_name_index,
)

logger = logging.getLogger(__name__)

OWNER_USER_ID = ""
PROTECTED_OWNER_RE = re.compile(r"(?:owner|master|主人|主子)", re.I)
STABLE_FACT_OPERATOR_RE = re.compile(r"(?:喜欢|讨厌|不喜欢|会|擅长|正在学|学习|经常|平时|习惯|外号|昵称|通常被叫|被叫作|被称作)", re.I)
TRANSIENT_OR_EVENT_RE = re.compile(r"(?:今天|刚才|现在|正在哭|哭了|被窝|签到|天气|B站|视频解析|生成图片|指令|命令|/|http|https|CQ:)", re.I)

@dataclass(frozen=True)
class RenderableFact:
    predicate: str
    text: str
    priority: float = 0.5

@dataclass(frozen=True)
class ResolvedProfileTarget:
    user_id: str
    display_name: str = ""
    matched_term: str = ""
    reason: str = ""
    score: float = 0.0
    aliases: tuple[str, ...] = ()
    facts: tuple[RenderableFact, ...] = ()

@dataclass(frozen=True)
class ProfileAnswerResult:
    handled: bool
    reply: str = ""
    frame: MemoryDecisionFrame | None = None
    candidates: tuple[ResolvedProfileTarget, ...] = ()
    resolved: ResolvedProfileTarget | None = None


def _clean_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _clip(text: str, limit: int) -> str:
    clean = _clean_spaces(text)
    return clean if len(clean) <= limit else clean[: max(1, limit - 1)].rstrip("，、；;：: ") + "…"


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


def _features(observation: Observation) -> dict[str, Any]:
    return getattr(observation, "features", {}) or {}


def _sender_id(observation: Observation) -> str:
    return str(getattr(observation, "sender_id", "") or getattr(observation, "user_id", "") or "").strip()


def _scope_id(observation: Observation) -> str:
    return str(_features(observation).get("scope_id") or getattr(observation, "group_id", "") or "").strip()


def _debug_decision(frame: MemoryDecisionFrame, result: dict[str, Any] | None = None) -> None:
    if os.getenv("BOT_MEMORY_DECISION_DEBUG", "").lower() not in {"1", "true", "yes", "on"}:
        return
    payload = json.loads(frame.to_json())
    if result is not None:
        payload["memory_search_result"] = result
    logger.info("bot_memory_decision_frame=%s", json.dumps(payload, ensure_ascii=False))


def _store() -> Any | None:
    try:
        from src.chatbot.bot_brain.social_cognition.store import social_cognition_store
        return social_cognition_store
    except Exception:
        logger.exception("social_cognition_store unavailable")
        return None


def _norm_key(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _is_protected_owner_pollution(text: str, subject_user_id: str = "") -> bool:
    return bool(PROTECTED_OWNER_RE.search(str(text or ""))) and str(subject_user_id or "") != OWNER_USER_ID


def _user_rows(store: Any) -> list[dict[str, Any]]:
    try:
        store.initialize()
        with store.connect() as conn:
            rows = conn.execute("SELECT user_id, display_name, aliases_json FROM social_users").fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def _user_row(store: Any, user_id: str) -> dict[str, Any]:
    try:
        store.initialize()
        with store.connect() as conn:
            row = conn.execute("SELECT user_id, display_name, aliases_json FROM social_users WHERE user_id=?", (str(user_id),)).fetchone()
            return dict(row) if row else {"user_id": str(user_id), "display_name": "", "aliases_json": "[]"}
    except Exception:
        return {"user_id": str(user_id), "display_name": "", "aliases_json": "[]"}


def _memory_rows_for_user(store: Any, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    try:
        rows = store.memories_for_user(user_id, limit=limit)
        return [dict(r) for r in (rows or [])]
    except Exception:
        pass
    try:
        store.initialize()
        with store.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM social_memories
                WHERE subject_user_id=? AND is_active=1 AND confidence>=0.2
                ORDER BY (priority * 0.55 + confidence * 0.45) DESC, updated_at DESC
                LIMIT ?
                """,
                (str(user_id), limit),
            ).fetchall()
            return [dict(row) for row in rows]
    except Exception:
        return []


def _all_active_memory_rows(store: Any, limit: int = 1000) -> list[dict[str, Any]]:
    try:
        store.initialize()
        with store.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM social_memories
                WHERE is_active=1 AND confidence>=0.2
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
    except Exception:
        return []


def _display_and_aliases(store: Any, user_id: str, fallback_display: str = "") -> tuple[str, list[str]]:
    row = _user_row(store, user_id)
    display = str(row.get("display_name") or "").strip()
    if not is_label_like(display, max_len=20):
        display = ""
    if not display and fallback_display and is_label_like(fallback_display, max_len=20):
        display = fallback_display.strip()
    aliases = [a for a in _safe_json_list(row.get("aliases_json")) if is_label_like(a)]
    if display and display not in aliases:
        aliases.insert(0, display)
    return display, list(dict.fromkeys(aliases))


def _alias_from_memory_text(text: str, tags: Iterable[str] = (), source_type: str = "") -> str:
    # Only alias/nickname typed rows may create identity candidates. Arbitrary fact
    # body hits are explicitly not identity evidence.
    tagset = {str(t) for t in tags}
    if not (tagset & {"alias", "nickname", "admin_confirmed"} or source_type in {"admin_said", "self_said"}):
        return ""
    raw = str(text or "")
    patterns = (
        r"被称作[“\"']([^”\"']{1,24})[”\"']",
        r"被叫作[“\"']([^”\"']{1,24})[”\"']",
        r"(?:昵称|外号)(?:是|叫)?[“\"']?([^”\"'，。；;\s]{1,24})[”\"']?",
        r"大家(?:通常|一般)?叫(?:他|她|ta|TA)?[“\"']?([^”\"'，。；;\s]{1,24})[”\"']?",
        r"(?:叫我|我叫|可以叫我)\s*([A-Za-z0-9_\-\u4e00-\u9fff·・ー]{1,24})",
    )
    for pattern in patterns:
        m = re.search(pattern, raw, re.I)
        if m:
            alias = m.group(1).strip()
            if is_label_like(alias, max_len=16):
                return alias
    return ""


def _sanitize_memory_text(text: str) -> str:
    t = _clean_spaces(text)
    t = SYSTEM_TRACE_RE.sub("", t)
    t = re.sub(r"(?:该群友|这个群友|这个人|这人)自述[:：]?", "自己说过", t)
    t = re.sub(r"(?:该群友|这个群友|这个人|这人)", "", t)
    t = re.sub(r"有人(?:说|描述|提到)", "有人提过", t)
    t = re.sub(r"\s+", " ", t).strip(" ，,。；;：:")
    return t


def renderable_fact_from_row(row: dict[str, Any]) -> RenderableFact | None:
    text = str(row.get("memory_text") or "")
    subject = str(row.get("subject_user_id") or "")
    if not text or _is_protected_owner_pollution(text, subject):
        return None
    tags = _safe_json_list(row.get("tags_json"))
    source = str(row.get("source_type") or "")
    alias = _alias_from_memory_text(text, tags, source)
    if alias:
        return RenderableFact("alias", f"通常被叫作“{alias}”", 0.95)
    clean = _sanitize_memory_text(text)
    if not clean or SYSTEM_TRACE_RE.search(clean) or _is_protected_owner_pollution(clean, subject):
        return None
    if TRANSIENT_OR_EVENT_RE.search(clean):
        return None
    tagset = set(tags)
    if tagset & {"command", "plugin_output", "llm_output", "roleplay", "transient_event"}:
        return None
    # Stable facts must be operator-driven or explicitly typed. Raw random body is
    # not renderable.
    if not (tagset & {"skill", "preference", "habit", "profile", "identity_role", "self_profile"} or STABLE_FACT_OPERATOR_RE.search(clean)):
        return None
    clean = clean.replace("自己说过喜欢", "喜欢")
    clean = clean.replace("自己说过会", "会")
    clean = clean.replace("自己说过擅长", "擅长")
    clean = clean.replace("自己说过正在", "正在")
    return RenderableFact("profile", _clip(clean, 38), 0.65)


def _resolve_direct_user(store: Any, user_id: str, display_hint: str = "") -> ResolvedProfileTarget | None:
    uid = str(user_id or "").strip()
    if not uid:
        return None
    display, aliases = _display_and_aliases(store, uid, display_hint)
    facts: list[RenderableFact] = []
    for row in _memory_rows_for_user(store, uid):
        fact = renderable_fact_from_row(row)
        if fact and fact.text not in [f.text for f in facts]:
            facts.append(fact)
            if fact.predicate == "alias":
                alias = re.sub(r"^通常被叫作[“\"']?|[”\"']$", "", fact.text).strip("。“”\"'")
                if alias and alias not in aliases and is_label_like(alias):
                    aliases.append(alias)
    return ResolvedProfileTarget(uid, display, reason="direct_user", score=1.0, aliases=tuple(aliases), facts=tuple(facts[:8]))


def resolve_exact_alias_candidates(store: Any, terms: list[str], *, top_k: int = 12, scope_id: str = "") -> list[ResolvedProfileTarget]:
    """Resolve identity candidates only through the clean alias/name index.

    This prevents arbitrary memory-body matches from becoming identity evidence.
    The index itself only accepts typed alias/display_name/nickname evidence.
    """
    matches = search_alias_name_index(store, terms, scope_id=scope_id, top_k=top_k)
    out: list[ResolvedProfileTarget] = []
    for match in matches:
        target = _resolve_direct_user(store, match.user_id, match.display_name or match.label)
        if not target:
            continue
        aliases = list(target.aliases)
        if match.label and match.label not in aliases and is_label_like(match.label, max_len=16):
            aliases.insert(0, match.label)
        score = 1.0 if match.label_type == "display_name" else 0.96
        score += min(0.03, (float(match.confidence) + float(match.priority)) / 100.0)
        out.append(ResolvedProfileTarget(
            target.user_id,
            target.display_name or match.display_name or match.label,
            matched_term=match.label,
            reason="clean_alias_name_index",
            score=score,
            aliases=tuple(aliases[:8]),
            facts=target.facts,
        ))
    out.sort(key=lambda c: (-c.score, c.display_name or c.user_id))
    return out[:top_k]


def resolve_alias_candidates(store: Any, terms: list[str], *, top_k: int = 12, scope_id: str = "") -> list[ResolvedProfileTarget]:
    return resolve_exact_alias_candidates(store, terms, top_k=top_k, scope_id=scope_id)


def inspect_alias_candidates(store: Any, term: str, *, scope_id: str = "", top_k: int = 20) -> list[dict[str, Any]]:
    return inspect_alias_name(store, term, scope_id=scope_id, top_k=top_k)

def _target_label(target: ResolvedProfileTarget, fallback: str = "这位群友") -> str:
    for value in (target.display_name, *(target.aliases or ())):
        if value and is_label_like(value, max_len=20):
            return value
    # Last-resort persona-facing fallback must be a noun phrase, not "这位";
    # otherwise reply templates produce "这位这位".
    return fallback


def _facts_sentence(facts: Iterable[RenderableFact]) -> str:
    items: list[str] = []
    for fact in sorted(facts, key=lambda f: -f.priority):
        text = _clean_spaces(fact.text).strip("。")
        if not text or SYSTEM_TRACE_RE.search(text) or PROTECTED_OWNER_RE.search(text):
            continue
        text = re.sub(r"^(?:我印象里|本人说过|有人提过)[:：]?", "", text).strip()
        if text not in items:
            items.append(text)
    if not items:
        return "我对他的印象还不多，先不装熟啦。"
    if len(items) == 1:
        return f"我印象里，{items[0]}。"
    return "我印象里，" + "，".join(items[:4]) + "。"


def _sanitize_reply(text: str, max_length: int = 420) -> str:
    clean = _clean_spaces(text)
    clean = re.sub(r"通常通常", "通常", clean)
    clean = re.sub(r"我我", "我", clean)
    clean = SYSTEM_TRACE_RE.sub("", clean)
    clean = re.sub(r"\s+", " ", clean).strip(" ，,。；;：:")
    try:
        from src.chatbot.bot_brain.natural_output import guard_natural_output_reply
        guarded = guard_natural_output_reply(clean, max_length=max_length)
        if guarded:
            clean = guarded
    except Exception:
        pass
    return _clip(clean or "嗯…我刚才没对上，别让我乱编啦。", max_length)


def _not_found(term: str = "这个人") -> str:
    t = _clean_spaces(term) or "这个人"
    return f"嗯…{t}我暂时没对上是哪位，别让我乱认啦。你 @ 一下或回复那个人，我就能接上。"


def _ambiguous_reply(term: str, candidates: list[ResolvedProfileTarget], *, enumerate_mode: bool = False) -> str:
    t = _clean_spaces(term) or "这个称呼"
    if not candidates:
        return _not_found(t)
    rows: list[str] = []
    for c in candidates[:8]:
        name = _target_label(c)
        at = f"[CQ:at,qq={c.user_id}]" if c.user_id and c.user_id != OWNER_USER_ID else name
        aliases = [a for a in c.aliases if a != name and is_label_like(a)][:2]
        hint = f"（也叫{'、'.join(aliases)}）" if aliases else ""
        rows.append(f"{at} {name}{hint}".strip())
    if enumerate_mode:
        return f"我对上了这些叫“{t}”的群友：" + "；".join(rows) + "。"
    return f"嗯…“{t}”我对上了不止一个人：" + "；".join(rows) + "。你指一下具体是哪位，我就不会乱认啦。"


def _single_reply(frame: MemoryDecisionFrame, target: ResolvedProfileTarget) -> str:
    name = _target_label(target)
    term = (target.matched_term or (frame.target.alias_terms[0] if frame.target.alias_terms else "")).strip()
    facts = _facts_sentence(target.facts)
    generic = name in {"这位", "这位群友", "这个群友"}
    if frame.intent == "sender_self_query":
        return (f"嗯，我记得你是{name}。" if not generic else "嗯，我对上你了。") + facts
    if term and term != name and not generic:
        return f"嗯，我对上了，{term}是{name}这位。" + facts
    if generic:
        return "嗯，我对上了，是这位群友。" + facts
    return f"嗯，我对上了，是{name}这位。" + facts


def is_profile_memory_query(observation: Observation) -> bool:
    frame = build_memory_decision_frame(observation)
    _debug_decision(frame)
    return bool(frame.search_memory or frame.routing.get("block_normal_llm_when_handled"))


def answer_profile_memory_query_if_any(observation: Observation, *legacy_args: Any, max_length: int = 420) -> str:
    if not is_profile_memory_query(observation):
        return ""
    return answer_profile_memory_query(observation, *legacy_args, max_length=max_length)


def answer_profile_memory_query(observation: Observation, *legacy_args: Any, max_length: int = 420) -> str:
    result = answer_profile_memory_query_result(observation, *legacy_args, max_length=max_length)
    return result.reply if result.handled else ""


def answer_profile_memory_query_result(observation: Observation, *legacy_args: Any, max_length: int = 420) -> ProfileAnswerResult:
    frame = build_memory_decision_frame(observation)
    if frame.intent == "bot_self_query":
        return ProfileAnswerResult(False, frame=frame)
    if frame.intent == "sender_self_query" and str(frame.target.user_id or "") == OWNER_USER_ID:
        # Owner self-identity is governed by the protected-identity context and
        # final guard, not by generic social profile memories. This avoids stale
        # profile facts overriding the stable owner boundary.
        return ProfileAnswerResult(False, frame=frame)
    if not frame.search_memory and not frame.routing.get("block_normal_llm_when_handled"):
        return ProfileAnswerResult(False, frame=frame)
    store = _store()
    if store is None:
        return ProfileAnswerResult(True, _sanitize_reply("嗯…我现在没连上群友记忆，先别让我乱认啦。", max_length), frame=frame)
    try:
        store.initialize()
    except Exception:
        return ProfileAnswerResult(True, _sanitize_reply("嗯…群友记忆刚才卡住了，你再 @ 一下我重新对。", max_length), frame=frame)

    try:
        from src.chatbot.bot_brain.social_arch.profile_query_runtime import ProfileQueryRuntime

        # Explicit "把叫 X 的群友 @ 出来" is a transport-rendering command.
        # Keep it on the legacy compatibility branch for now so mention markup
        # stays at the adapter boundary instead of entering SafePersonaContext.
        if frame.intent != "alias_enumeration_query":
            runtime_result = ProfileQueryRuntime(store).answer(observation, max_length=max_length)
            if runtime_result.handled and runtime_result.reply:
                resolved = None
                if runtime_result.context is not None:
                    trace_id = str(runtime_result.context.internal_trace.target_identity_id or "")
                    if trace_id:
                        resolved = _resolve_direct_user(store, trace_id)
                return ProfileAnswerResult(True, runtime_result.reply, frame=frame, resolved=resolved)
    except Exception:
        logger.exception("P1 profile query runtime failed; falling back to legacy profile_answerer")

    # Legacy deterministic path retained only as a compatibility fallback until
    # ReplyOrchestrator owns natural profile replies end to end. Do not expand
    # the template surface here; add structured runtime behavior instead.
    if frame.intent == "ambiguous_pronoun_query":
        return ProfileAnswerResult(True, _sanitize_reply("嗯…这个‘他’我没对上是哪位，你 @ 一下或回复那个人，我就能接上。", max_length), frame=frame)

    mode = str(frame.memory_query.get("mode") or "")
    candidates: list[ResolvedProfileTarget] = []
    if mode == "by_user_id" or frame.target.user_id:
        target = _resolve_direct_user(store, frame.target.user_id or str(frame.memory_query.get("user_id") or ""), frame.target.display_name)
        candidates = [target] if target else []
    elif mode in {"resolve_exact_alias", "enumerate_exact_alias"}:
        terms = list(frame.target.alias_terms or frame.memory_query.get("terms") or [])
        candidates = resolve_exact_alias_candidates(store, terms, top_k=int(frame.memory_query.get("top_k") or 12), scope_id=str(frame.memory_query.get("scope_id") or ""))

    if mode == "enumerate_exact_alias":
        term = frame.target.alias_terms[0] if frame.target.alias_terms else "这个称呼"
        reply = _ambiguous_reply(term, candidates, enumerate_mode=True) if candidates else _not_found(term)
        _debug_decision(frame, {"mode": mode, "candidate_user_ids": [c.user_id for c in candidates]})
        return ProfileAnswerResult(True, _sanitize_reply(reply, max_length), frame=frame, candidates=tuple(candidates))

    if not candidates:
        term = frame.target.display_name or (frame.target.alias_terms[0] if frame.target.alias_terms else "这个人")
        return ProfileAnswerResult(True, _sanitize_reply(_not_found(term), max_length), frame=frame)

    if mode == "by_user_id" and len(candidates) == 1 and not candidates[0].facts:
        return ProfileAnswerResult(False, frame=frame)

    if len(candidates) > 1:
        best, second = candidates[0], candidates[1]
        term = best.matched_term or (frame.target.alias_terms[0] if frame.target.alias_terms else "这个称呼")
        # Only auto-resolve if the top candidate is exact and the second is clearly weaker.
        if best.score >= 0.98 and second.score < 0.88:
            reply = _single_reply(frame, best)
            _debug_decision(frame, {"resolved_user_id": best.user_id, "candidate_count": len(candidates)})
            return ProfileAnswerResult(True, _sanitize_reply(reply, max_length), frame=frame, resolved=best, candidates=tuple(candidates))
        reply = _ambiguous_reply(term, candidates)
        _debug_decision(frame, {"ambiguous_candidates": [c.user_id for c in candidates]})
        return ProfileAnswerResult(True, _sanitize_reply(reply, max_length), frame=frame, candidates=tuple(candidates))

    target = candidates[0]
    reply = _single_reply(frame, target)
    _debug_decision(frame, {"resolved_user_id": target.user_id, "candidate_count": 1})
    return ProfileAnswerResult(True, _sanitize_reply(reply, max_length), frame=frame, resolved=target, candidates=tuple(candidates))
