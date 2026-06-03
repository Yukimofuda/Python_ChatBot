from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

try:
    from src.chatbot.bot_brain.models import Observation
except Exception:  # pragma: no cover
    Observation = Any  # type: ignore
try:
    from src.chatbot.bot_brain.observation import ObservationNormalizer
    from src.chatbot.bot_brain.observation.normalizer import strip_bot_rendered_text
except Exception:  # pragma: no cover
    ObservationNormalizer = None  # type: ignore
    strip_bot_rendered_text = None  # type: ignore

MemoryIntent = Literal[
    "bot_self_query",
    "sender_self_query",
    "target_identity_query",
    "target_profile_query",
    "alias_enumeration_query",
    "ambiguous_pronoun_query",
    "non_profile_query",
]
TargetKind = Literal[
    "bot_self",
    "current_sender",
    "mention_user",
    "reply_sender",
    "previous_context_user",
    "qq_id",
    "alias_literal",
    "enumeration_alias",
    "ambiguous_pronoun",
    "none",
]

# System/provenance terms are never persona-facing. This regex is intentionally
# category-level rather than example-level.
SYSTEM_TRACE_RE = re.compile(
    r"(管理员(?:确认|那边|说)|数据库|系统记录|后台|检索(?:结果)?|记录显示|可靠记录|观测记录|内部记录|审计|migration|source_type|confidence|ProfileQueryAnswerContract|ResolvedTargetUserId|群友认知参考|该群友(?:自述)?)",
    re.I,
)

CQ_RE = re.compile(r"\[CQ:[^\]]+\]")
AT_QQ_RE = re.compile(r"\[CQ:at,qq=(\d+)\]|\[at:qq=(\d+)\]|@\s*(\d{5,12})")
REPLY_TEXT_RE = re.compile(r"\[回复消息\s*\[([^\](]{1,40})\((\d{5,12})\)\]", re.I)
QQ_RE = re.compile(r"(?<!\d)(\d{5,12})(?!\d)")
COMMAND_RE = re.compile(r"^\s*[/!！]")

# Explicit intent operators. A bare noun/adjective/reaction is not enough.
BOT_SELF_QUERY_RE = re.compile(
    r"^\s*(?:你是谁|你是誰|你叫什么|你叫什麼|你叫啥|你是什么|你是机器人吗|你是哪位|介绍一下你自己|自我介绍)\s*[？?。.!！]*\s*$"
)
SENDER_SELF_QUERY_RE = re.compile(
    r"^\s*(?:我是谁|我是誰|那我是谁|那么我是谁|所以我是谁|你记得我吗|记得我吗|你认识我吗|认识我吗|认得我吗|你知道我是谁吗|说说我|评价一下我|我是哪位|我是什么人)\s*[？?。.!！]*\s*$"
)
AMBIGUOUS_PRONOUN_RE = re.compile(
    r"^\s*(?:他|她|ta|TA|这个人|这人|这个群友|那个人|这位|那位)\s*(?:是谁|是誰|是哪位|是哪个群友|哪个群友|是什么人|什么人|叫什么|叫啥|叫啥名|名字|叫什麼|加什么|加什麼|你记得吗|记得吗|有什么印象|什么印象|怎么样|怎样的人|什么样的人)?\s*[？?。.!！]*\s*$"
)
PROFILE_OPERATOR_RE = re.compile(
    r"(?:是谁|是誰|是哪个群友|哪个群友|是哪位|是哪一个|是什么人|什么人|叫什么|叫啥|叫啥名|名字|叫什麼|叫咩|加什么|加什麼|怎么样|怎样的人|什么样的人|有什么印象|什么印象|有什么特点|特点|你记得|记得.*吗|认得.*吗|认识.*吗|了解.*吗|说说|评价|描述)",
    re.I,
)
ENUMERATION_RE_LIST = [
    re.compile(r"^(?:把)?(?:所有|全部|群里|这个群里)?(?:叫|被叫|称作|外号是|昵称是)(?P<term>[^？?。.!！]{1,24}?)(?:的)?(?:人|群友)?(?:都|全部)?(?:@出来|艾特出来|列出来|是谁|有哪些|都有谁|哪几个|哪几位)\s*[？?。.!！]*$", re.I),
    re.compile(r"^(?P<term>[^？?。.!！]{1,24}?)(?:都有谁|有哪些人|有哪些群友|是哪几个|是哪几位|分别是谁)\s*[？?。.!！]*$", re.I),
    re.compile(r"^(?:谁|哪些人|哪些群友)(?:叫|被叫|称作|外号是|昵称是)(?P<term>[^？?。.!！]{1,24}?)\s*[？?。.!！]*$", re.I),
]
QUERY_TERM_PATTERNS = [
    re.compile(r"^(?P<term>.+?)(?:是谁|是誰|是哪个群友|哪个群友|是哪位|是哪一个|是什么人|什么人|叫什么|叫啥|叫啥名|名字|叫什麼|怎么样|怎样的人|什么样的人|有什么特点|特点)\s*[？?。.!！]*$", re.I),
    re.compile(r"^(?:你)?(?:记得|认得|认识|了解)(?P<term>.+?)(?:吗|么|嘛|呢|[？?。.!！])*$", re.I),
    re.compile(r"^(?:说说|评价一下|描述一下)(?P<term>.+?)\s*[？?。.!！]*$", re.I),
    re.compile(r"^(?:对|关于)(?P<term>.+?)(?:的)?(?:印象|评价|了解)\s*[？?。.!！]*$", re.I),
]

@dataclass
class MemoryDecisionTarget:
    kind: TargetKind = "none"
    user_id: str = ""
    display_name: str = ""
    alias_terms: list[str] = field(default_factory=list)
    from_reply: bool = False
    from_mention: bool = False
    source: str = ""

@dataclass
class MemoryDecisionFrame:
    frame_version: str = "bot_memory_decision_v21"
    search_memory: bool = False
    intent: MemoryIntent = "non_profile_query"
    target: MemoryDecisionTarget = field(default_factory=MemoryDecisionTarget)
    memory_query: dict[str, Any] = field(default_factory=dict)
    routing: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2, sort_keys=False)


def _clean_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _features(observation: Observation) -> dict[str, Any]:
    return getattr(observation, "features", {}) or {}


def _text(observation: Observation) -> str:
    raw = str(getattr(observation, "raw_message_text", "") or getattr(observation, "text", "") or "")
    return str(getattr(observation, "text", "") or raw).strip()


def _raw_text(observation: Observation) -> str:
    return str(getattr(observation, "raw_message_text", "") or getattr(observation, "text", "") or "").strip()


def _sender_id(observation: Observation) -> str:
    return str(getattr(observation, "sender_id", "") or getattr(observation, "user_id", "") or "").strip()


def _scope_id(observation: Observation) -> str:
    f = _features(observation)
    return str(f.get("scope_id") or getattr(observation, "group_id", "") or "").strip()


def _bot_id(observation: Observation) -> str:
    f = _features(observation)
    return str(f.get("bot_id") or f.get("self_id") or getattr(observation, "self_id", "") or "").strip()


def strip_bot_mentions(text: str) -> str:
    if strip_bot_rendered_text is not None:
        return strip_bot_rendered_text(text)
    clean = re.sub(r"\[CQ:at,qq=\d+\]", " ", str(text or ""))
    clean = re.sub(r"\[at:qq=\d+\]", " ", clean)
    clean = CQ_RE.sub(" ", clean)
    clean = re.sub(r"^(?:@?\s*(?:Bot|Bot|Bot|Bot|Bot))\s+", " ", clean, flags=re.I)
    return _clean_spaces(clean)


def mentioned_user_ids(observation: Observation) -> list[str]:
    ids: list[Any] = list(getattr(observation, "mentioned_user_ids", None) or [])
    f = _features(observation)
    for key in ("mentioned_user_ids", "mentions", "at_user_ids"):
        value = f.get(key)
        if isinstance(value, list):
            ids.extend(value)
    raw = _raw_text(observation)
    for m in AT_QQ_RE.finditer(raw):
        ids.extend([g for g in m.groups() if g])
    bot = _bot_id(observation)
    out: list[str] = []
    for uid in ids:
        s = str(uid or "").strip()
        if s and s != bot and s not in out:
            out.append(s)
    return out


def mentioned_display_name(observation: Observation, user_id: str) -> str:
    f = _features(observation)
    maps = [
        getattr(observation, "mentioned_display_names", None),
        getattr(observation, "mentioned_user_display_names", None),
        f.get("mentioned_display_names"),
        f.get("mentioned_user_display_names"),
    ]
    for mapping in maps:
        if isinstance(mapping, dict):
            value = str(mapping.get(str(user_id)) or "").strip()
            if value:
                return value
    return ""


def reply_sender(observation: Observation) -> tuple[str, str, str]:
    f = _features(observation)
    uid = name = content = ""
    for key in ("reply_user_id", "replied_user_id", "reply_sender_id", "reply_to_user_id", "quoted_user_id", "source_user_id"):
        if str(f.get(key) or "").strip():
            uid = str(f.get(key)).strip(); break
    for key in ("reply_sender_display_name", "replied_sender_display_name", "reply_display_name", "quoted_display_name", "reply_nickname"):
        if str(f.get(key) or "").strip():
            name = str(f.get(key)).strip(); break
    for key in ("reply_message_text", "replied_message_text", "quoted_text", "source_message_text"):
        if str(f.get(key) or "").strip():
            content = str(f.get(key)).strip(); break
    m = REPLY_TEXT_RE.search(_raw_text(observation))
    if m:
        name = name or m.group(1).strip()
        uid = uid or m.group(2).strip()
    return uid, name, content


def previous_context_user(observation: Observation) -> tuple[str, str]:
    f = _features(observation)
    for uid_key, name_key in (("previous_user_id", "previous_display_name"), ("last_user_id", "last_display_name"), ("context_user_id", "context_display_name")):
        uid = str(f.get(uid_key) or "").strip()
        if uid:
            return uid, str(f.get(name_key) or "").strip()
    return "", ""


def _label_like(term: str) -> bool:
    t = str(term or "").strip()
    if not (1 <= len(t) <= 24):
        return False
    if SYSTEM_TRACE_RE.search(t):
        return False
    # Labels should not be full clauses/sentences. This is structural: punctuation,
    # whitespace-heavy phrases, or common clause particles disqualify it.
    if re.search(r"[，。！？!?；;：:、\n\r\t]", t):
        return False
    if len(re.findall(r"[的了着过是把被在和与及或但因为所以如果然后]|[A-Za-z]+|\d+", t)) > 5 and len(t) > 10:
        return False
    if re.search(r"(这个|那个|一种|一条|一句|自己|大家|有人|真的|就是).{2,}", t) and len(t) > 8:
        return False
    return True


def _normalize_term(term: str) -> str:
    t = str(term or "")
    t = CQ_RE.sub(" ", t)
    t = re.sub(r"@\S+", " ", t)
    t = _clean_spaces(t)
    t = t.strip(" 的他她它这个人这个群友这人那个人这位那位：:；;（）()[]【】<>《》'\"“”‘’")
    if t in {"他", "她", "ta", "TA", "这个人", "这人", "这个群友", "那个人", "这位", "那位", "我", "你", ""}:
        return ""
    if re.fullmatch(r"\d{5,12}", t):
        return t
    return t if _label_like(t) else ""


def extract_enumeration_term(text: str) -> str:
    compact = re.sub(r"\s+", "", strip_bot_mentions(text))
    for pattern in ENUMERATION_RE_LIST:
        m = pattern.match(compact)
        if m:
            term = _normalize_term(m.group("term"))
            if term:
                return term
    return ""


def extract_query_terms(text: str) -> list[str]:
    compact = re.sub(r"\s+", "", strip_bot_mentions(text))
    if not compact or AMBIGUOUS_PRONOUN_RE.match(compact):
        return []
    terms: list[str] = []
    enum = extract_enumeration_term(text)
    if enum:
        terms.append(enum)
    for pattern in QUERY_TERM_PATTERNS:
        m = pattern.match(compact)
        if m:
            terms.append(m.group("term"))
    out: list[str] = []
    for term in terms:
        norm = _normalize_term(term)
        if norm and norm not in out:
            out.append(norm)
    return out[:5]


def build_memory_decision_frame(observation: Observation) -> MemoryDecisionFrame:
    normalized = ObservationNormalizer().normalize(observation) if ObservationNormalizer is not None else None
    raw = normalized.raw_text if normalized is not None else _raw_text(observation)
    text = normalized.text if normalized is not None else strip_bot_mentions(_text(observation))
    sender = normalized.sender_internal_key if normalized is not None else _sender_id(observation)
    scope_id = normalized.scope_id if normalized is not None else _scope_id(observation)
    mentions = list(normalized.mentioned_internal_keys) if normalized is not None else mentioned_user_ids(observation)
    if normalized is not None:
        reply_uid, reply_name, reply_text = (
            normalized.reply_target.internal_key,
            normalized.reply_target.display_name,
            normalized.reply_target.text,
        )
    else:
        reply_uid, reply_name, reply_text = reply_sender(observation)
    prev_uid, prev_name = previous_context_user(observation)
    terms = extract_query_terms(text)
    frame = MemoryDecisionFrame()
    frame.evidence = {
        "raw_text": raw,
        "normalized_text": text,
        "sender_id": sender,
        "sender_display_name": str(getattr(observation, "sender_display_name", "") or _features(observation).get("sender_display_name") or ""),
        "scope_id": scope_id,
        "mentioned_user_ids": mentions,
        "reply_user_id": reply_uid,
        "reply_display_name": reply_name,
        "previous_user_id": prev_uid,
        "previous_display_name": prev_name,
        "query_terms": terms,
    }
    frame.routing = {
        "block_normal_llm_when_handled": False,
        "policy": "typed_intent_slot_target_sanitized_answer",
    }

    if not text or COMMAND_RE.match(text):
        return frame
    if BOT_SELF_QUERY_RE.match(text):
        frame.intent = "bot_self_query"
        frame.target = MemoryDecisionTarget(kind="bot_self", source="bot_self_query")
        return frame
    if SENDER_SELF_QUERY_RE.match(text):
        frame.intent = "sender_self_query"; frame.search_memory = True
        frame.target = MemoryDecisionTarget(kind="current_sender", user_id=sender, display_name=str(frame.evidence.get("sender_display_name") or ""), source="sender_self_query")
        frame.memory_query = {"mode": "by_user_id", "user_id": sender, "scope_id": scope_id, "top_k": 8}
        frame.routing["block_normal_llm_when_handled"] = True
        return frame

    enum_term = extract_enumeration_term(text)
    if enum_term:
        frame.intent = "alias_enumeration_query"; frame.search_memory = True
        frame.target = MemoryDecisionTarget(kind="enumeration_alias", alias_terms=[enum_term], source="enumeration_alias_literal")
        frame.memory_query = {"mode": "enumerate_exact_alias", "terms": [enum_term], "scope_id": scope_id, "top_k": 12}
        frame.routing["block_normal_llm_when_handled"] = True
        return frame

    has_profile_operator = bool(PROFILE_OPERATOR_RE.search(text))
    pronoun_query = bool(AMBIGUOUS_PRONOUN_RE.match(text))
    if not (has_profile_operator or pronoun_query):
        return frame

    if len(mentions) == 1:
        uid = mentions[0]
        frame.intent = "target_identity_query"; frame.search_memory = True
        frame.target = MemoryDecisionTarget(kind="mention_user", user_id=uid, display_name=mentioned_display_name(observation, uid), from_mention=True, source="mention_user")
        frame.memory_query = {"mode": "by_user_id", "user_id": uid, "scope_id": scope_id, "top_k": 8}
        frame.routing["block_normal_llm_when_handled"] = True
        return frame
    if len(mentions) > 1:
        frame.intent = "ambiguous_pronoun_query"
        frame.target = MemoryDecisionTarget(kind="ambiguous_pronoun", source="multi_mention")
        frame.routing["block_normal_llm_when_handled"] = True
        frame.evidence["candidate_user_ids"] = mentions
        return frame

    if pronoun_query:
        if reply_uid:
            frame.intent = "target_identity_query"; frame.search_memory = True
            frame.target = MemoryDecisionTarget(kind="reply_sender", user_id=reply_uid, display_name=reply_name, from_reply=True, source="reply_sender")
            frame.memory_query = {"mode": "by_user_id", "user_id": reply_uid, "scope_id": scope_id, "top_k": 8}
            frame.routing["block_normal_llm_when_handled"] = True
            return frame
        if prev_uid:
            frame.intent = "target_identity_query"; frame.search_memory = True
            frame.target = MemoryDecisionTarget(kind="previous_context_user", user_id=prev_uid, display_name=prev_name, source="previous_context_user")
            frame.memory_query = {"mode": "by_user_id", "user_id": prev_uid, "scope_id": scope_id, "top_k": 8}
            frame.routing["block_normal_llm_when_handled"] = True
            return frame
        frame.intent = "ambiguous_pronoun_query"
        frame.target = MemoryDecisionTarget(kind="ambiguous_pronoun", source="pronoun_without_target")
        frame.routing["block_normal_llm_when_handled"] = True
        return frame

    if terms:
        qq_terms = [t for t in terms if re.fullmatch(r"\d{5,12}", t)]
        if qq_terms:
            uid = qq_terms[0]
            frame.intent = "target_identity_query"; frame.search_memory = True
            frame.target = MemoryDecisionTarget(kind="qq_id", user_id=uid, alias_terms=terms, source="qq_id")
            frame.memory_query = {"mode": "by_user_id", "user_id": uid, "scope_id": scope_id, "top_k": 8}
        else:
            frame.intent = "target_identity_query"; frame.search_memory = True
            frame.target = MemoryDecisionTarget(kind="alias_literal", alias_terms=terms, source="alias_literal")
            frame.memory_query = {"mode": "resolve_exact_alias", "terms": terms, "scope_id": scope_id, "top_k": 12}
        frame.routing["block_normal_llm_when_handled"] = True
        return frame
    return frame


def decision_frame_to_prompt_context(frame: MemoryDecisionFrame) -> str:
    """Debug-only summary. Do not put this into persona-facing LLM prompts."""
    if not frame.search_memory:
        return ""
    return frame.to_json()
