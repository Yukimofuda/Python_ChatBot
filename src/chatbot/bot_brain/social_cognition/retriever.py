from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from src.chatbot.bot_brain.models import Observation
from src.chatbot.bot_brain.natural_output import naturalize_memory_text_for_prompt, naturalize_source_label

from .extractor import get_bot_id, get_mentioned_user_ids, get_scope_id, get_sender_id
from .policy import is_identity_request, public_no_identity_reply_context

PROFILE_QUERY_RE = re.compile(
    r"(是谁|是怎样的人|怎么样|怎样的人|什么样|你记得.*吗|记得我吗|我是谁|平时怎么样|评价一下|了解.*吗|印象|说说.*这个人|描述一下)"
)
PRONOUN_MENTION_QUERY_RE = re.compile(
    r"(他是谁|她是谁|这个人是谁|这人是谁|ta是谁|TA是谁|他怎么样|她怎么样|这个人怎么样|这人怎么样)"
)
SELF_PROFILE_QUERY_RE = re.compile(r"(我是谁|你记得我吗|记得我吗|你认识我吗|了解我吗)")


@dataclass(frozen=True)
class SocialRetrievalResult:
    target_user_id: str | None = None
    context: str = ""
    memory_ids: list[str] = field(default_factory=list)
    privacy_blocked: bool = False
    no_memory: bool = False
    resolved_subject: str | None = None


def is_profile_query(text: str) -> bool:
    return bool(PROFILE_QUERY_RE.search(text or ""))


def is_pronoun_mention_query(text: str) -> bool:
    return bool(PRONOUN_MENTION_QUERY_RE.search(text or ""))


def is_self_profile_query(text: str) -> bool:
    return bool(SELF_PROFILE_QUERY_RE.search(text or ""))


def _bot_ids_from_observation(observation: Observation) -> set[str]:
    features = getattr(observation, "features", {}) or {}
    ids = {get_bot_id(observation)}
    for key in ("bot_id", "self_id", "bot_self_id"):
        value = features.get(key)
        if value:
            ids.add(str(value))
    return {uid for uid in ids if uid}


def _dedupe(seq: list[str]) -> list[str]:
    return list(dict.fromkeys([str(x) for x in seq if str(x or "").strip()]))




def _sanitize_persona_facing_context(text: str) -> str:
    """Return only persona-facing memory context.

    Retrieval may internally know target_user_id, source_type, confidence and
    audit metadata. Those belong to structured fields/logs, not to the text
    prompt that Bot may imitate. This sanitizer is the final boundary before
    the generator sees social-memory context.
    """
    if not text:
        return ""
    forbidden_tokens = (
        "ProfileQueryAnswerContract",
        "ResolvedTargetUserId",
        "AnswerObligation",
        "群友认知参考",
        "管理员确认",
        "管理员那边",
        "管理员说",
        "数据库",
        "系统记录",
        "后台记录",
        "后台",
        "检索结果",
        "检索",
        "记录显示",
        "我这边只有记录",
        "我这里只有记录",
        "可靠记录",
        "内部记录",
        "审计",
        "migration",
        "source_type",
        "confidence",
        "该群友自述",
        "该群友",
    )
    bad_guidance_lines = (
        "回答时像自然想起来一样说，不要提来源、系统、后台或字段。",
        "回答时像自然想起来一样说，不要提来源、系统、或字段。",
        "回答时像自然想起来一样说，不要提来源、后台或字段。",
        "回答时自然一点，先说想起来的印象。",
    )
    cleaned = text
    for line in bad_guidance_lines:
        cleaned = cleaned.replace("\n" + line, "")
        cleaned = cleaned.replace(line, "")
    for token in forbidden_tokens:
        cleaned = cleaned.replace(token, "")
    lines: list[str] = []
    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Drop leftover pure meta-instruction lines. Persona-facing context should
        # be memories/impressions, not instructions about hidden machinery.
        if line.startswith("回答时") or line.startswith("不要"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


class SocialRetriever:
    """Retrieve platform-user-keyed social memory and render persona-facing context.

    Boundary contract:
    - target_user_id, source_type, confidence and audit remain structured/internal;
    - result.context is allowed to be passed to the LLM and therefore must be
      natural, human-readable memory context;
    - result.context must not contain control-protocol names, database terms,
      provenance labels, or implementation fields.
    """

    def __init__(self, store):
        self.store = store

    def retrieve(self, observation: Observation, *, limit: int = 5) -> SocialRetrievalResult:
        return self.retrieve_for_observation(observation, limit=limit)

    def retrieve_for_observation(self, observation: Observation, *, limit: int = 5) -> SocialRetrievalResult:
        text = str(getattr(observation, "text", "") or "")
        wants_public_qq = is_identity_request(text)
        profile_query = is_profile_query(text) or wants_public_qq

        sender_id = get_sender_id(observation)
        scope_id = get_scope_id(observation)
        bot_ids = _bot_ids_from_observation(observation)
        mentioned_targets = [
            uid for uid in get_mentioned_user_ids(observation)
            if uid and uid != sender_id and uid not in bot_ids
        ]

        targets: list[str] = []
        if is_self_profile_query(text) and sender_id:
            targets.append(sender_id)
        elif is_pronoun_mention_query(text):
            if len(mentioned_targets) == 1:
                targets.append(mentioned_targets[0])
            elif len(mentioned_targets) > 1:
                return SocialRetrievalResult(
                    context="我现在不太确定你问的是哪一位，可以再明确一下。",
                    no_memory=True,
                )
        else:
            targets.extend(mentioned_targets)

        if profile_query:
            resolver = getattr(self.store, "resolver", None)
            if resolver is not None and hasattr(resolver, "candidate_user_ids_from_text"):
                try:
                    targets.extend(resolver.candidate_user_ids_from_text(text, scope_id=scope_id))
                except TypeError:
                    targets.extend(resolver.candidate_user_ids_from_text(text))
            if hasattr(self.store, "candidate_user_ids_from_text"):
                targets.extend(self.store.candidate_user_ids_from_text(text, scope_id=scope_id))

        targets = _dedupe(targets)[:3]
        if not targets:
            if wants_public_qq:
                return SocialRetrievalResult(
                    context=public_no_identity_reply_context(),
                    privacy_blocked=False,
                    no_memory=True,
                )
            return SocialRetrievalResult()

        chunks: list[str] = []
        ids: list[str] = []
        for target in targets:
            memories = self.store.memories_for_user(target, query=text, scope_id=scope_id, limit=limit)
            if not memories:
                continue
            ids.extend([str(m.get("id") or "") for m in memories if m.get("id")])
            rendered = self._render_target_context(memories)
            if rendered:
                chunks.append(rendered)

        if not chunks:
            return SocialRetrievalResult(
                target_user_id=targets[0],
                context="我现在还没想起足够稳定的印象，不敢乱编。",
                no_memory=True,
                resolved_subject=targets[0],
            )

        body = "\n".join(chunks)
        context = "我能想起来的印象：\n" + body
        if wants_public_qq:
            context += "\n如果用户明确问账号或 账号 ID，可以在不泄露其他隐私的前提下回答已解析到的公开群身份。"
        else:
            context += ""
        return SocialRetrievalResult(
            target_user_id=targets[0],
            context=_sanitize_persona_facing_context(context),
            memory_ids=ids[:limit],
            resolved_subject=targets[0],
        )

    def _render_target_context(self, memories: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for memory in memories:
            memory_text = naturalize_memory_text_for_prompt(str(memory.get("memory_text") or ""))
            if not memory_text:
                continue
            label = naturalize_source_label(str(memory.get("source_type") or ""), float(memory.get("confidence") or 0.0))
            line = f"- {label}：{memory_text}" if label else f"- {memory_text}"
            line = self._strip_internal_tokens(line)
            if line:
                lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _strip_internal_tokens(text: str) -> str:
        replacements = {
            "管理员确认": "我印象里",
            "管理员那边": "我印象里",
            "数据库": "印象",
            "系统记录": "印象",
            "后台": "这边",
            "检索结果": "回想起来",
            "检索": "回想",
            "记录显示": "我印象里",
            "我这边只有记录": "我印象里",
            "可靠记录": "稳定印象",
            "ProfileQueryAnswerContract": "",
            "ResolvedTargetUserId": "",
            "AnswerObligation": "",
            "source_type": "",
            "confidence": "",
            "该群友自述": "自己说过",
            "该群友": "",
            "群友认知参考": "我能想起来的印象",
        }
        clean = str(text or "")
        for old, new in replacements.items():
            clean = clean.replace(old, new)
        clean = re.sub(r"\s+", " ", clean).strip()
        clean = clean.replace(" ：", "：").replace("- ：", "-")
        return clean

# --- PHASE6_CONTEXTUAL_RECALL_V12 monkey patch ---
# Keep internal control data out of persona-facing context. Retrieval result fields
# may carry target_user_id/memory_ids, but `context` must be natural memory text only.
try:
    from src.chatbot.bot_brain.social_cognition.conversation_context import (
        clean_persona_context,
        extract_reply_metadata,
        is_profile_like_query,
        is_pronoun_or_reply_query,
        is_self_query,
        naturalize_memory_text,
        recent_context_lines,
        scan_alias_targets,
    )
except Exception:  # pragma: no cover
    clean_persona_context = lambda s: str(s or "")
    naturalize_memory_text = lambda s: str(s or "")
    scan_alias_targets = lambda *a, **k: []
    recent_context_lines = lambda *a, **k: []
    is_profile_like_query = lambda s: False
    is_pronoun_or_reply_query = lambda s: False
    is_self_query = lambda s: False


def _phase12_features(observation):
    features = getattr(observation, "features", {}) or {}
    return features if isinstance(features, dict) else {}


def _phase12_scope_id(observation):
    features = _phase12_features(observation)
    return str(features.get("scope_id") or features.get("group_id") or getattr(observation, "group_id", "") or "")


def _phase12_sender_id(observation):
    features = _phase12_features(observation)
    return str(getattr(observation, "sender_id", "") or features.get("sender_id") or getattr(observation, "user_id", "") or "")


def _phase12_bot_ids(observation):
    features = _phase12_features(observation)
    ids = {str(features.get(k) or "") for k in ("bot_id", "self_id", "bot_self_id")}
    return {x for x in ids if x}


def _phase12_mentioned_user_ids(observation):
    features = _phase12_features(observation)
    raw = getattr(observation, "mentioned_user_ids", None) or features.get("mentioned_user_ids") or []
    if not isinstance(raw, list):
        return []
    sender = _phase12_sender_id(observation)
    bot_ids = _phase12_bot_ids(observation)
    return [str(x) for x in raw if str(x) and str(x) != sender and str(x) not in bot_ids]


def _phase12_reply_sender_id(observation):
    features = _phase12_features(observation)
    rid = str(features.get("reply_sender_id") or "").strip()
    if rid:
        return rid
    meta = extract_reply_metadata({}, text=str(getattr(observation, "text", "") or ""), raw_message_text=str(getattr(observation, "raw_message_text", "") or features.get("raw_message_text") or ""))
    return str(meta.get("reply_sender_id") or "").strip()


def _phase12_resolve_targets(self, observation, *, profile_query=False, wants_public_qq=False):
    text = str(getattr(observation, "text", "") or "")
    scope_id = _phase12_scope_id(observation)
    mentioned = _phase12_mentioned_user_ids(observation)
    targets = []
    resolved = None
    hard = False

    if is_self_query(text):
        sender = _phase12_sender_id(observation)
        if sender:
            return [sender], resolved, False

    if len(mentioned) == 1 and (is_profile_like_query(text) or is_pronoun_or_reply_query(text) or wants_public_qq):
        targets.append(mentioned[0])
        hard = True

    reply_sender = _phase12_reply_sender_id(observation)
    if reply_sender and (is_pronoun_or_reply_query(text) or is_profile_like_query(text)):
        targets.append(reply_sender)

    if is_profile_like_query(text) or wants_public_qq:
        # Local active alias scan is intentionally independent of the old resolver,
        # because live failures showed alias memories can exist while the LLM still
        # receives no usable target context.
        targets.extend(scan_alias_targets(self.store, text, scope_id=scope_id, limit=3))
        try:
            if hasattr(self.store, "candidate_user_ids_from_text"):
                targets.extend(self.store.candidate_user_ids_from_text(text, scope_id=scope_id))
        except Exception:
            pass

    uniq = []
    for uid in targets:
        uid = str(uid or "").strip()
        if uid and uid not in uniq:
            uniq.append(uid)
    return uniq[:3], resolved, hard


def _phase12_render_target_context(self, memories):
    lines = []
    for memory in memories or []:
        raw = str(memory.get("memory_text") or "")
        line = naturalize_memory_text(raw)
        if line:
            prefix = "我印象里："
            source = str(memory.get("source_type") or "")
            if source == "self_said":
                prefix = "自己说过："
            elif source == "other_said":
                prefix = "有人提过："
            lines.append(f"- {prefix}{line}")
    return "\n".join(lines[:5])


def _phase12_retrieve_for_observation(self, observation, *, limit=5):
    text = str(getattr(observation, "text", "") or "")
    wants_public_qq = is_identity_request(text)
    profile_query = is_profile_like_query(text) or is_self_query(text) or is_pronoun_or_reply_query(text)
    targets, resolved, hard = _phase12_resolve_targets(self, observation, profile_query=profile_query, wants_public_qq=wants_public_qq)
    scope_id = _phase12_scope_id(observation)

    if not targets:
        if is_pronoun_or_reply_query(text) or is_profile_like_query(text):
            context_lines = recent_context_lines(self.store, scope_id, limit=2)
            ctx = "我暂时没对上你说的是哪位。"
            if context_lines:
                ctx += "\n刚才能参考到的聊天：\n" + "\n".join(f"- {line}" for line in context_lines)
            return SocialRetrievalResult(context=clean_persona_context(ctx), no_memory=True)
        return SocialRetrievalResult()

    target = targets[0]
    try:
        memories = self.store.memories_for_user(target, query=text, scope_id=scope_id, limit=limit)
    except TypeError:
        memories = self.store.memories_for_user(target, limit=limit)
    ids = [str(m.get("id") or "") for m in memories if m.get("id")]
    rendered = _phase12_render_target_context(self, memories)
    if rendered:
        parts = ["群友认知参考："]
        if hard:
            parts.append("当前问题里的‘他/她/这个人’已经解析为这个群友；直接回答，不要反问，不要把问题转成 Bot 自我介绍。")
        if hard or wants_public_qq:
            parts.append("当前问题已经解析到目标群友；不要要求用户重新提供名字或昵称。")
        parts.append("我能想起来的印象：")
        parts.append(rendered)
        context = "\n".join(parts)
        cleaned = clean_persona_context(context)
        if not cleaned.startswith("群友认知参考"):
            cleaned = "群友认知参考：\n" + cleaned
        return SocialRetrievalResult(target_user_id=target, resolved_subject=resolved or target, context=cleaned, memory_ids=ids, no_memory=False)
    context = "群友认知参考：当前问题在询问已解析群友，但没有足够可靠的长期印象。"
    if hard:
        context += "\n当前问题里的‘他/她/这个人’已经解析为这个群友；直接回答，不要反问，不要把问题转成 Bot 自我介绍。"
    cleaned = clean_persona_context(context)
    if not cleaned.startswith("群友认知参考"):
        cleaned = "群友认知参考：" + cleaned
    return SocialRetrievalResult(target_user_id=target, resolved_subject=resolved or target, context=cleaned, memory_ids=[], no_memory=True)


SocialRetriever._resolve_targets = _phase12_resolve_targets
SocialRetriever._render_target_context = _phase12_render_target_context
SocialRetriever.retrieve_for_observation = _phase12_retrieve_for_observation
# --- END PHASE6_CONTEXTUAL_RECALL_V12 ---

# --- PHASE6_OWNER_POLLUTION_CONTEXT_FILTER_V12_1 ---
# Persona-facing memory context must not include protected owner identity pollution.
# This is a retrieval/context-builder gate, not a final-output bandage.
try:
    import re as _phase12_1_re
except Exception:  # pragma: no cover
    _phase12_1_re = None

_PHASE12_1_OWNER_ID = ""
_PHASE12_1_OWNER_POLLUTION_RE = _phase12_1_re.compile(
    r"(主人|绑定主人|owner|owner|owner|乱写的主人|Bot\s*的主人|Bot.*主人|Bot.*主人)",
    _phase12_1_re.I,
) if _phase12_1_re else None


def _phase12_1_is_owner_polluted_memory(memory):
    if not isinstance(memory, dict):
        return False
    subject = str(memory.get("subject_user_id") or memory.get("user_id") or "")
    raw = str(memory.get("memory_text") or memory.get("value") or "")
    if not raw or _PHASE12_1_OWNER_POLLUTION_RE is None:
        return False
    if subject == _PHASE12_1_OWNER_ID:
        return "" in raw
    return bool(_PHASE12_1_OWNER_POLLUTION_RE.search(raw))


def _phase12_1_render_target_context(self, memories):
    lines = []
    for memory in memories or []:
        if _phase12_1_is_owner_polluted_memory(memory):
            continue
        raw = str(memory.get("memory_text") or "")
        try:
            line = naturalize_memory_text(raw)
        except Exception:
            line = raw
        if not line:
            continue
        if _PHASE12_1_OWNER_POLLUTION_RE is not None and _PHASE12_1_OWNER_POLLUTION_RE.search(line):
            continue
        source = str(memory.get("source_type") or "")
        prefix = "我印象里："
        if source == "self_said":
            prefix = "自己说过："
        elif source == "other_said":
            prefix = "有人提过："
        lines.append(f"- {prefix}{line}")
    return "\n".join(lines[:5])


SocialRetriever._render_target_context = _phase12_1_render_target_context
try:
    _phase12_render_target_context = _phase12_1_render_target_context  # type: ignore[name-defined]
except Exception:
    pass
# --- END PHASE6_OWNER_POLLUTION_CONTEXT_FILTER_V12_1 ---

# --- PHASE6_PERSONA_MEMORY_CONTRACT_V12_2 ---
# System invariant:
# - Internal source/trust/audit may exist in storage and ranking.
# - Persona-facing context must contain only natural memory impressions.
# - Owner/owner/master pollution is filtered before prompt construction.
# - No negative instruction text such as "do not mention backend" is allowed in result.context.
try:
    import re as _phase12_2_re
except Exception:  # pragma: no cover
    _phase12_2_re = None

_PHASE12_2_OWNER_ID = ""
_PHASE12_2_OWNER_POLLUTION_RE = _phase12_2_re.compile(
    r"(主人|绑定主人|owner|owner|owner|乱写的主人|Bot\s*的主人|Bot.*主人|Bot.*主人)",
    _phase12_2_re.I,
) if _phase12_2_re else None
_PHASE12_2_SYSTEM_TRACE_RE = _phase12_2_re.compile(
    r"(管理员确认|管理员那边|管理员说|数据库|系统记录|后台|检索结果|检索|记录显示|我这边只有记录|我这里只有记录|可靠记录|内部记录|后台记录|审计|migration|source_type|confidence|ResolvedTargetUserId|ProfileQueryAnswerContract|AnswerObligation|群友认知参考|不要提来源|不要提|字段|该群友自述|该群友)",
    _phase12_2_re.I,
) if _phase12_2_re else None


def _phase12_2_memory_text(memory):
    if not isinstance(memory, dict):
        return ""
    return str(
        memory.get("memory_text")
        or memory.get("raw_evidence")
        or memory.get("evidence_text")
        or memory.get("value")
        or ""
    )


def _phase12_2_is_owner_polluted_memory(memory):
    if not isinstance(memory, dict) or _PHASE12_2_OWNER_POLLUTION_RE is None:
        return False
    subject = str(memory.get("subject_user_id") or memory.get("user_id") or "")
    raw = _phase12_2_memory_text(memory)
    if not raw:
        return False
    if subject == _PHASE12_2_OWNER_ID:
        # For the real owner, do not leak protected numeric identity through context.
        return "" in raw
    return bool(_PHASE12_2_OWNER_POLLUTION_RE.search(raw))


def _phase12_2_clean_persona_line(text):
    line = str(text or "").strip()
    if not line:
        return ""
    # Convert common storage/reporting wording into natural memory wording.
    replacements = {
        "管理员确认": "",
        "管理员那边确认过": "",
        "管理员那边": "",
        "管理员说": "",
        "数据库里": "",
        "数据库": "",
        "系统记录显示": "",
        "系统记录": "",
        "后台查到": "",
        "后台": "",
        "检索结果显示": "",
        "检索结果": "",
        "检索": "",
        "记录显示": "",
        "我这边只有记录": "",
        "我这里只有记录": "",
        "可靠记录": "",
        "可靠信息": "",
        "内部记录": "",
        "后台记录": "",
        "该群友自述：": "自己说过：",
        "该群友自述": "自己说过",
        "该群友": "",
        "这个群友": "",
    }
    for old, new in replacements.items():
        line = line.replace(old, new)
    if _phase12_2_re:
        line = _phase12_2_re.sub(r"\s+", " ", line).strip()
        line = _phase12_2_re.sub(r"^[：:，,。\s]+", "", line).strip()
        line = _phase12_2_re.sub(r"\s*被称作\s*", "通常被叫作", line)
        line = line.replace("通常被叫作“", "通常被叫作“")
    return line.strip(" ，,。")


def _phase12_2_persona_memory_line(memory):
    if _phase12_2_is_owner_polluted_memory(memory):
        return ""
    raw = _phase12_2_memory_text(memory)
    if not raw:
        return ""
    try:
        line = naturalize_memory_text(raw)  # type: ignore[name-defined]
    except Exception:
        line = raw
    line = _phase12_2_clean_persona_line(line)
    if not line:
        return ""
    if _PHASE12_2_OWNER_POLLUTION_RE is not None and _PHASE12_2_OWNER_POLLUTION_RE.search(line):
        return ""
    if _PHASE12_2_SYSTEM_TRACE_RE is not None:
        # Last cleanup pass; if any system trace remains after cleanup, drop the line.
        line2 = _PHASE12_2_SYSTEM_TRACE_RE.sub("", line).strip()
        line2 = _phase12_2_clean_persona_line(line2)
        if not line2 or (_PHASE12_2_SYSTEM_TRACE_RE.search(line2) if _PHASE12_2_SYSTEM_TRACE_RE else False):
            return ""
        line = line2
    source = str(memory.get("source_type") or "")
    if source == "self_said":
        prefix = "自己说过："
    elif source == "other_said":
        prefix = "有人提过："
    else:
        prefix = "我印象里："
    if line.startswith(("我印象里：", "自己说过：", "有人提过：")):
        return f"- {line}"
    return f"- {prefix}{line}。"


def _phase12_2_render_target_context(self, memories):
    lines = []
    seen = set()
    for memory in memories or []:
        line = _phase12_2_persona_memory_line(memory)
        if not line:
            continue
        key = line.strip()
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)
    return "\n".join(lines[:5])


# Override both method and legacy module-level hook used by earlier v12 patches.
SocialRetriever._render_target_context = _phase12_2_render_target_context
try:
    _phase12_render_target_context = _phase12_2_render_target_context  # type: ignore[name-defined]
except Exception:
    pass
# --- END PHASE6_PERSONA_MEMORY_CONTRACT_V12_2 ---
