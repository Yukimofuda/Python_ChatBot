from __future__ import annotations

import os
import re
from typing import Any, Protocol

from src.chatbot.bot_brain.models import Observation

from .policy import (
    contains_offensive_judgement,
    contains_sensitive_private_info,
    is_safe_alias,
    normalize_alias,
    redact_sensitive,
)
from .memory_gate import CandidateMemory

FACT_TRIGGER_RE = re.compile(
    r"(是|像|属于|喜欢|讨厌|不喜欢|会|擅长|正在|最近在|经常|总是|平时|习惯|别叫|可以叫|叫他|叫她|记住|记得|印象|很会|折腾)"
)
SELF_FACT_RE = re.compile(
    r"(^|[，。,.!！?？\s])(我是|我叫|我喜欢|我讨厌|我不喜欢|我会|我擅长|我正在|我最近在|我经常|我平时|别叫我|可以叫我|记住我|记得我)"
)
SELF_ALIAS_PATTERNS = (
    re.compile(r"(?:^|[，。,.!！?？\s])(?:叫我|可以叫我|我叫|我的外号是)\s*([A-Za-z0-9_\-\u4e00-\u9fff·・ー]{1,24})", re.I),
)
TARGET_ALIAS_PATTERNS = (
    re.compile(r"(?:这个群友|这个人|这人|他|她)\s*叫\s*([A-Za-z0-9_\-\u4e00-\u9fff·・ー]{1,24})", re.I),
    re.compile(r"(?:记住|记得|记一下|记下来)?\s*(?:这个群友|这个人|这人|他|她)\s*是\s*([A-Za-z0-9_\-\u4e00-\u9fff·・ー]{1,24})", re.I),
    re.compile(r"(?:以后叫|可以叫)(?:他|她)\s*([A-Za-z0-9_\-\u4e00-\u9fff·・ー]{1,24})", re.I),
    re.compile(r"叫(?:他|她)\s*([A-Za-z0-9_\-\u4e00-\u9fff·・ー]{1,24})\s*就行", re.I),
    re.compile(r"(?:他|她)的外号是\s*([A-Za-z0-9_\-\u4e00-\u9fff·・ー]{1,24})", re.I),
    re.compile(r"(?:大家|群里一般)叫(?:他|她)\s*([A-Za-z0-9_\-\u4e00-\u9fff·・ー]{1,24})", re.I),
    re.compile(r"(?:他|她)一般被叫\s*([A-Za-z0-9_\-\u4e00-\u9fff·・ー]{1,24})", re.I),
    re.compile(r"([A-Za-z0-9_\-\u4e00-\u9fff·・ー]{1,24})\s*就是(?:这个人|这个群友|刚才\s*@\s*的这个|刚才@的这个)", re.I),
    re.compile(r"(?:以后说|我说的|提到)\s*([A-Za-z0-9_\-\u4e00-\u9fff·・ー]{1,24})\s*就是(?:他|她|这个群友|这个人)", re.I),
)
TAG_RULES: tuple[tuple[str, str], ...] = (
    ("linux", "linux"),
    ("rust", "rust"),
    ("python", "python"),
    ("nonebot", "nonebot"),
    ("napcat", "napcat"),
    ("修", "skill"),
    ("擅长", "skill"),
    ("很会", "skill"),
    ("喜欢", "preference"),
    ("讨厌", "preference"),
    ("经常", "habit"),
    ("平时", "habit"),
)
COMMAND_PREFIXES = ("/", "!", "！")


DEFAULT_ADMIN_IDS = set()


class SubjectResolverProtocol(Protocol):
    def resolve_ref(self, reference: str, *, scope_id: str | None = None): ...
    def resolve_unique_non_bot_mention(self, observation: Observation): ...


def _configured_admin_ids() -> set[str]:
    raw = os.getenv("CHATBOT_SOCIAL_COGNITION_ADMIN_IDS") or os.getenv("CHATBOT_ADMIN_IDS") or ""
    ids = {part.strip() for part in re.split(r"[,;\s]+", raw) if part.strip()}
    return ids or set(DEFAULT_ADMIN_IDS)


def _is_admin_source(user_id: str) -> bool:
    return str(user_id or "").strip() in _configured_admin_ids()


def _is_identifier_assertion(text: str) -> bool:
    clean = str(text or "")
    return bool(re.search(r"(?:QQ\s*号|qq\s*号|user[_-]?id|uid|账号|帐号)\s*(?:是|=|:|：)?\s*\d{5,12}", clean, re.I))


def _is_memory_pollution_text(text: str) -> bool:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return True
    if _is_question(clean):
        return True
    pollution_patterns = (
        r"爱丽丝正在思考中",
        r"接收到.*(?:指令|命令)",
        r"纯颜文字|颜文字专属|语音包|静音挑战|主线任务|副本世界",
        r"老师.*(?:指令|带她|探索|保证)",
        r"此处根据实际上下文补一句",
        r"我没太听明白|再说清楚一点",
        r"\(.*?\).*\(.*?\).*\(.*?\)",
    )
    return any(re.search(pattern, clean, re.I) for pattern in pollution_patterns)


SocialMemoryCandidate = CandidateMemory
CandidateMemoryClaim = CandidateMemory


def get_sender_id(observation: Observation) -> str:
    return str(getattr(observation, "sender_id", None) or getattr(observation, "user_id", "") or "")


def get_scope_id(observation: Observation) -> str:
    group_id = str(getattr(observation, "group_id", "") or "")
    if group_id.startswith(("group:", "private:")):
        return group_id
    if str(getattr(observation, "message_type", "")) == "group" and group_id:
        return f"group:{group_id}"
    return group_id or "global"


def get_mentioned_user_ids(observation: Observation) -> list[str]:
    direct = getattr(observation, "mentioned_user_ids", None) or []
    if direct:
        return [str(x) for x in direct if str(x)]
    features = getattr(observation, "features", {}) or {}
    raw = features.get("mentioned_user_ids") or []
    return [str(x) for x in raw if str(x)] if isinstance(raw, list) else []


def get_bot_id(observation: Observation) -> str:
    features = getattr(observation, "features", {}) or {}
    for key in ("bot_id", "self_id", "bot_self_id"):
        value = features.get(key)
        if value:
            return str(value)
    return ""


def get_mentioned_display_names(observation: Observation) -> dict[str, str]:
    direct = getattr(observation, "mentioned_display_names", None) or {}
    if direct:
        return {str(k): str(v) for k, v in direct.items() if str(k) and str(v)}
    features = getattr(observation, "features", {}) or {}
    raw = features.get("mentioned_display_names") or features.get("mentioned_user_display_names") or {}
    return {str(k): str(v) for k, v in raw.items() if str(k) and str(v)} if isinstance(raw, dict) else {}


def get_sender_display_name(observation: Observation) -> str:
    direct = str(getattr(observation, "sender_display_name", "") or "")
    if direct:
        return direct
    features = getattr(observation, "features", {}) or {}
    return str(features.get("sender_display_name") or "")


def perception_from_observation(observation: Observation) -> dict[str, Any]:
    return {
        "text": str(getattr(observation, "text", "") or ""),
        "raw_message_text": str(getattr(observation, "raw_message_text", "") or getattr(observation, "text", "") or ""),
        "sender_id": get_sender_id(observation),
        "scope_id": get_scope_id(observation),
        "bot_id": get_bot_id(observation),
        "mentioned_user_ids": get_mentioned_user_ids(observation),
    }


def extract_tags(text: str) -> list[str]:
    lowered = (text or "").lower()
    tags: list[str] = []
    for needle, tag in TAG_RULES:
        if needle.lower() in lowered and tag not in tags:
            tags.append(tag)
    return tags[:8]


def _clip(text: str, limit: int = 700) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    return clean[:limit]


def _is_question(text: str) -> bool:
    clean = str(text or "").strip()
    if not clean:
        return False
    if "?" in clean or "？" in clean:
        return True
    if clean.endswith(("吗", "嗎", "么", "呢")):
        return True
    return bool(re.search(r"(?:^|[，。,.!！?？\s])(我是谁|他是谁|她是谁|这个群友是谁|这个人是谁|谁是|是什么|什么意思|几点|时间|日期)(?:$|[，。,.!！?？\s])", clean))


def _alias_pattern_matched(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in (*SELF_ALIAS_PATTERNS, *TARGET_ALIAS_PATTERNS))


def _non_bot_mentioned_from_perception(perception: dict[str, Any]) -> list[str]:
    sender_id = str(perception.get("sender_id") or "")
    bot_id = str(perception.get("bot_id") or "")
    result: list[str] = []
    for uid in perception.get("mentioned_user_ids") or []:
        sid = str(uid)
        if sid and sid != sender_id and sid != bot_id and sid not in result:
            result.append(sid)
    return result


def non_bot_mentioned_user_ids(observation: Observation) -> list[str]:
    return _non_bot_mentioned_from_perception(perception_from_observation(observation))


def _first_alias_match(text: str, patterns: tuple[re.Pattern[str], ...]) -> str:
    for pattern in patterns:
        match = pattern.search(text or "")
        if not match:
            continue
        alias = normalize_alias(match.group(1))
        if is_safe_alias(alias) and not _looks_like_attribute_phrase(alias):
            return alias
    return ""


def _looks_like_attribute_phrase(value: str) -> bool:
    clean = str(value or "").strip()
    return bool(re.search(r"(很会|会修|擅长|喜欢|讨厌|经常|平时|习惯|正在|最近|高手|大佬|大神)", clean))


def extract_alias_claims(perception: dict[str, Any]) -> list[CandidateMemoryClaim]:
    plain = _clip(str(perception.get("text") or perception.get("raw_message_text") or ""), 700)
    raw = _clip(str(perception.get("raw_message_text") or plain), 700)
    if not plain or plain.lstrip().startswith(COMMAND_PREFIXES):
        return []
    if _is_identifier_assertion(plain) or _is_memory_pollution_text(plain):
        return []
    if _is_question(plain) or contains_sensitive_private_info(plain):
        return []

    sender_id = str(perception.get("sender_id") or "")
    scope_id = str(perception.get("scope_id") or "global")
    if not sender_id:
        return []

    self_alias = _first_alias_match(plain, SELF_ALIAS_PATTERNS)
    if self_alias:
        return [
            CandidateMemoryClaim(
                subject_user_id=sender_id,
                source_user_id=sender_id,
                source_type="self_said",
                predicate="alias",
                value=self_alias,
                evidence_text=redact_sensitive(raw),
                confidence=0.85,
                priority=0.75,
                scope_id=scope_id,
                emotion_valence=0.0,
                tags=["alias", "nickname"],
            )
        ]

    target_alias = _first_alias_match(plain, TARGET_ALIAS_PATTERNS)
    if not target_alias:
        return []
    targets = _non_bot_mentioned_from_perception(perception)
    if len(targets) != 1:
        return []
    admin_source = _is_admin_source(sender_id)
    return [
        CandidateMemoryClaim(
            subject_user_id=targets[0],
            source_user_id=sender_id,
            source_type="admin_said" if admin_source else "other_said",
            predicate="alias",
            value=target_alias,
            evidence_text=redact_sensitive(raw),
            confidence=0.9 if admin_source else 0.55,
            priority=0.85 if admin_source else 0.70,
            scope_id=scope_id,
            emotion_valence=0.0,
            tags=["alias", "nickname", "admin_confirmed"] if admin_source else ["alias", "nickname"],
        )
    ]


def extract_alias_claim(observation: Observation) -> SocialMemoryCandidate | None:
    claims = extract_alias_claims(perception_from_observation(observation))
    return claims[0] if claims else None


def _candidate_values_for_self_profile(text: str) -> list[tuple[str, str, list[str]]]:
    clean = str(text or "")
    values: list[tuple[str, str, list[str]]] = []
    alias = _first_alias_match(clean, SELF_ALIAS_PATTERNS)
    if alias:
        values.append(("alias", alias, ["alias", "nickname", "self_profile"]))
    for match in re.finditer(r"我(?:喜欢|爱)\s*([A-Za-z0-9_\-\u4e00-\u9fff +#/.]{1,40})", clean, re.I):
        values.append(("preference", match.group(1).strip(" ，。,.!！?？"), ["preference", "self_profile"]))
    for match in re.finditer(r"我(?:会|擅长|很会)\s*([A-Za-z0-9_\-\u4e00-\u9fff +#/.]{1,40})", clean, re.I):
        values.append(("skill", match.group(1).strip(" ，。,.!！?？"), ["skill", "self_profile"]))
    if not values and SELF_FACT_RE.search(clean):
        values.append(("self_profile", redact_sensitive(clean), ["self_profile", *extract_tags(clean)]))
    return [(predicate, value, tags) for predicate, value, tags in values if value]


def _candidate_for_target_statement(text: str) -> tuple[str, str, list[str]] | None:
    """Extract statements whose subject is an explicit pronoun/mentioned target.

    Important Phase 3 boundary: alias/nickname claims such as “他是网管” are
    handled only by extract_alias_claims(). They must not also become
    identity_role/stable_impression memories, otherwise one utterance creates
    both “被称作网管” and “是网管”.
    """
    clean = str(text or "")
    if _first_alias_match(clean, TARGET_ALIAS_PATTERNS):
        return None
    match = re.search(r"(?:他|她|这个人|这个群友|这人).{0,8}(?:会|擅长|很会|能修|会修)\s*([A-Za-z0-9_\-\u4e00-\u9fff +#/.]{1,40})", clean, re.I)
    if match:
        return "skill", match.group(1).strip(" ，。,.!！?？"), ["skill"]
    match = re.search(r"(?:他|她|这个人|这个群友|这人).{0,8}(?:喜欢|爱)\s*([A-Za-z0-9_\-\u4e00-\u9fff +#/.]{1,40})", clean, re.I)
    if match:
        return "preference", match.group(1).strip(" ，。,.!！?？"), ["preference"]
    match = re.search(r"(?:他|她|这个人|这个群友|这人).{0,8}(?:经常|平时|习惯)\s*([A-Za-z0-9_\-\u4e00-\u9fff +#/.]{1,50})", clean, re.I)
    if match:
        return "habit", match.group(1).strip(" ，。,.!！?？"), ["habit"]
    if re.search(r"(?:他|她|这个人|这个群友|这人).{0,12}(?:是|像|属于|印象|性格)", clean):
        tags = extract_tags(clean)
        predicate = "skill" if "skill" in tags else "preference" if "preference" in tags else "stable_impression"
        return predicate, redact_sensitive(clean), tags or ["stable_impression"]
    return None


_ALIAS_LINKED_PATTERNS: tuple[tuple[re.Pattern[str], str, list[str]], ...] = (
    (re.compile(r"^(?:记住|记得|记一下|记下来)?\s*([A-Za-z0-9_\-\u4e00-\u9fff·・ー]{1,24})\s*是\s*(高手|大佬|大神|专家|能手)\s*$", re.I), "skill", ["skill", "stable_impression"]),
    (re.compile(r"^(?:记住|记得|记一下|记下来)?\s*([A-Za-z0-9_\-\u4e00-\u9fff·・ー]{1,24})\s*(?:会修|能修)\s*([A-Za-z0-9_\-\u4e00-\u9fff +#/.]{1,40})\s*$", re.I), "skill", ["skill"]),
    (re.compile(r"^(?:记住|记得|记一下|记下来)?\s*([A-Za-z0-9_\-\u4e00-\u9fff·・ー]{1,24})\s*(?:会|擅长|很会)\s*([A-Za-z0-9_\-\u4e00-\u9fff +#/.]{1,40})\s*$", re.I), "skill", ["skill"]),
    (re.compile(r"^(?:记住|记得|记一下|记下来)?\s*([A-Za-z0-9_\-\u4e00-\u9fff·・ー]{1,24})\s*(?:喜欢|爱)\s*([A-Za-z0-9_\-\u4e00-\u9fff +#/.]{1,40})\s*$", re.I), "preference", ["preference"]),
    (re.compile(r"^(?:记住|记得|记一下|记下来)?\s*([A-Za-z0-9_\-\u4e00-\u9fff·・ー]{1,24})\s*(?:经常|平时|习惯)\s*([A-Za-z0-9_\-\u4e00-\u9fff +#/.]{1,50})\s*$", re.I), "habit", ["habit"]),
)


def _looks_like_relationship_spoof(value: str) -> bool:
    return bool(re.search(r"(?:owner|owner|owner|owner).{0,16}(?:主人|主子|父亲|爸爸|妈妈|性奴|男娘|调教|恶堕|对象|老婆|老公)|(?:主人|主子|性奴|调教|恶堕)", str(value or ""), re.I))


def _resolve_alias_link_subject(
    alias: str,
    observation: Observation,
    *,
    resolver: SubjectResolverProtocol | None,
    scope_id: str,
):
    """Resolve an alias-like symbol to a subject.

    Alias is only a reference token. It is never treated as a person by itself.
    Resolution requires either a unique resolver hit or a unique non-bot mention
    in the same utterance. Ambiguous/unknown aliases do not produce memories.
    """
    alias = normalize_alias(alias)
    if not alias or not is_safe_alias(alias):
        return None
    if resolver is not None:
        try:
            resolved = resolver.resolve_ref(alias, scope_id=scope_id)
            if getattr(resolved, "ok", False):
                return resolved
        except Exception:
            pass
        try:
            mentioned = resolver.resolve_unique_non_bot_mention(observation)
            if getattr(mentioned, "ok", False):
                return mentioned
        except Exception:
            pass
    targets = non_bot_mentioned_user_ids(observation)
    if len(targets) == 1:
        class _Resolved:
            ok = True
            user_id = targets[0]
            matched_reference = alias
            reason = "unique_non_bot_mention"
        return _Resolved()
    return None


def _extract_alias_linked_claims(
    observation: Observation,
    *,
    resolver: SubjectResolverProtocol | None,
) -> list[SocialMemoryCandidate]:
    """Extract trusted claims whose grammatical subject is an alias token.

    System-level rule from agentmemory: nickname/alias is a plain character
    token and only a resolution clue. Further traits are written only when the
    speaker is the subject themself or an admin. Ordinary third-party claims may
    remain in social_interactions but must not become active profile memory.
    """
    text = _clip(getattr(observation, "raw_message_text", "") or getattr(observation, "text", ""), 700)
    clean = re.sub(r"\s+", "", text)
    if not clean:
        return []
    sender_id = get_sender_id(observation)
    scope_id = get_scope_id(observation)
    admin_source = _is_admin_source(sender_id)
    out: list[SocialMemoryCandidate] = []
    for pattern, predicate, base_tags in _ALIAS_LINKED_PATTERNS:
        match = pattern.match(clean)
        if not match:
            continue
        alias = normalize_alias(match.group(1))
        value = match.group(2).strip(" ，。,.!！?？")
        if not alias or not value or _looks_like_relationship_spoof(value):
            return []
        resolved = _resolve_alias_link_subject(alias, observation, resolver=resolver, scope_id=scope_id)
        if not resolved or not getattr(resolved, "ok", False):
            return []
        subject_id = str(getattr(resolved, "user_id", "") or "")
        self_source = sender_id == subject_id
        if not admin_source and not self_source:
            # Third-party alias claims are not trusted profile memories.
            return []
        tags = list(dict.fromkeys([*base_tags, *extract_tags(text), "alias_linked", f"alias:{alias}"]))
        if admin_source and "admin_confirmed" not in tags:
            tags.append("admin_confirmed")
        if self_source and "self_profile" not in tags:
            tags.append("self_profile")
        source_type = "admin_said" if admin_source else "self_said"
        # Keep alias and trait separated in value; memory_gate.normalize renders
        # it without treating the alias as an attribute.
        normalized_value = f"{alias}:{value}"
        out.append(
            SocialMemoryCandidate(
                subject_user_id=subject_id,
                source_user_id=sender_id,
                source_type=source_type,
                predicate=predicate,
                value=normalized_value,
                evidence_text=redact_sensitive(text),
                confidence=0.9 if admin_source else 0.82,
                priority=0.85 if admin_source else 0.75,
                scope_id=scope_id,
                emotion_valence=0.0,
                tags=tags,
            )
        )
        break
    return out

def _rejected_candidate(observation: Observation, predicate: str, reason_value: str = "") -> SocialMemoryCandidate | None:
    sender_id = get_sender_id(observation)
    if not sender_id:
        return None
    text = _clip(getattr(observation, "raw_message_text", "") or getattr(observation, "text", ""), 700)
    return SocialMemoryCandidate(
        subject_user_id=sender_id,
        source_user_id=sender_id,
        source_type="self_said",
        predicate=predicate,
        value=reason_value or text,
        evidence_text=redact_sensitive(text),
        confidence=0.0,
        priority=0.0,
        scope_id=get_scope_id(observation),
        tags=[predicate],
    )


def extract_social_memories(observation: Observation, resolver: SubjectResolverProtocol | None = None) -> list[SocialMemoryCandidate]:
    text = _clip(getattr(observation, "raw_message_text", "") or getattr(observation, "text", ""), 700)
    plain = _clip(getattr(observation, "text", "") or text, 700)

    # Phase 1 boundary: every turn must be classified before memory extraction.
    # Only MEMORY_WRITE may produce accepted social_memories; queries, commands,
    # owner-relation spoofing, low-information and prompt-injection-like inputs
    # remain in social_interactions only.
    from .intent import IntentType, allows_memory_extraction, classify_observation_intent

    intent = classify_observation_intent(observation)
    if not allows_memory_extraction(intent):
        rejected_predicate = {
            IntentType.TOOL_OR_COMMAND: "command",
            IntentType.PROFILE_QUERY: "question",
            IntentType.SELF_IDENTITY_QUERY: "question",
            IntentType.OWNER_RELATION_CLAIM: "relationship_spoof",
            IntentType.LOW_INFORMATION: "low_information",
            IntentType.PROMPT_INJECTION_LIKE: "prompt_injection",
        }.get(intent.intent)
        return [c for c in [_rejected_candidate(observation, rejected_predicate)] if c] if rejected_predicate else []

    if not plain or plain.lstrip().startswith(COMMAND_PREFIXES):
        return [c for c in [_rejected_candidate(observation, "command")] if c]
    if _is_question(plain):
        return [c for c in [_rejected_candidate(observation, "question")] if c]
    if _is_identifier_assertion(plain) or contains_sensitive_private_info(plain):
        return [c for c in [_rejected_candidate(observation, "unknown")] if c]
    if _is_memory_pollution_text(plain):
        predicate = "plugin_result" if re.search(r"(成功.*第\d+个|晚安成功|签到成功|打卡成功)", plain) else "llm_roleplay"
        return [c for c in [_rejected_candidate(observation, predicate)] if c]
    alias_claims = extract_alias_claims(perception_from_observation(observation))
    alias_linked_claims = _extract_alias_linked_claims(observation, resolver=resolver)
    if alias_linked_claims:
        return list(alias_claims) + alias_linked_claims
    if _alias_pattern_matched(plain) and not alias_claims and not re.search(r"(很会|会修|擅长|喜欢|经常|平时|习惯)", plain):
        return []
    if not FACT_TRIGGER_RE.search(plain):
        return alias_claims

    sender_id = get_sender_id(observation)
    if not sender_id:
        return []
    scope_id = get_scope_id(observation)
    offensive = contains_offensive_judgement(plain)
    tags = extract_tags(plain)
    if offensive and "low_confidence" not in tags:
        tags.extend(["low_confidence", "offensive"])

    mentioned_ids = non_bot_mentioned_user_ids(observation)
    candidates: list[SocialMemoryCandidate] = list(alias_claims)
    if SELF_FACT_RE.search(plain) and not mentioned_ids:
        for predicate, value, value_tags in _candidate_values_for_self_profile(plain):
            merged_tags = list(dict.fromkeys([*value_tags, *tags]))
            candidates.append(
                SocialMemoryCandidate(
                    subject_user_id=sender_id,
                    source_user_id=sender_id,
                    source_type="self_said",
                    predicate=predicate,
                    value=value,
                    evidence_text=redact_sensitive(text),
                    confidence=0.85 if not offensive else 0.25,
                    priority=0.75 if not offensive else 0.25,
                    scope_id=scope_id,
                    emotion_valence=-0.2 if offensive else 0.05,
                    tags=merged_tags,
                )
            )
    elif SELF_FACT_RE.search(plain) and mentioned_ids:
        candidates.append(
            SocialMemoryCandidate(
                subject_user_id=mentioned_ids[0],
                source_user_id=sender_id,
                source_type="admin_said" if _is_admin_source(sender_id) else "other_said",
                predicate="vague_statement",
                value=redact_sensitive(plain),
                evidence_text=redact_sensitive(text),
                confidence=0.0,
                priority=0.0,
                scope_id=scope_id,
                emotion_valence=-0.2 if offensive else 0.05,
                tags=tags,
            )
        )

    admin_source = _is_admin_source(sender_id)
    for uid in mentioned_ids[:5]:
        statement = _candidate_for_target_statement(plain)
        if not statement:
            continue
        predicate, value, value_tags = statement
        if any(c.subject_user_id == uid and c.predicate == predicate and c.value == value for c in candidates):
            continue
        source_type = "admin_said" if admin_source else "other_said"
        base_tags = list(dict.fromkeys([*value_tags, *tags]))
        if admin_source and "admin_confirmed" not in base_tags:
            base_tags.append("admin_confirmed")
        if not admin_source and "unverified_other_claim" not in base_tags:
            base_tags.append("unverified_other_claim")
        candidates.append(
            SocialMemoryCandidate(
                subject_user_id=uid,
                source_user_id=sender_id,
                source_type=source_type,
                predicate=predicate,
                value=value,
                evidence_text=redact_sensitive(text),
                confidence=0.9 if admin_source and not offensive else (0.45 if not offensive else 0.2),
                priority=0.85 if admin_source and not offensive else (0.65 if not offensive else 0.25),
                scope_id=scope_id,
                emotion_valence=-0.25 if offensive else 0.0,
                tags=base_tags,
            )
        )
    return candidates
