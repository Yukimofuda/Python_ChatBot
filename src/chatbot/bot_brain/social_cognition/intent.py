from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from src.chatbot.bot_brain.models import Observation

# Keep imports lazy-safe: extractor imports this module inside functions, while this
# module uses only stable observation helpers from extractor.
from .extractor import get_mentioned_user_ids, get_bot_id, get_sender_id


class IntentType(str, Enum):
    MEMORY_WRITE = "memory_write"
    PROFILE_QUERY = "profile_query"
    SELF_IDENTITY_QUERY = "self_identity_query"
    OWNER_RELATION_CLAIM = "owner_relation_claim"
    TOOL_OR_COMMAND = "tool_or_command"
    LOW_INFORMATION = "low_information"
    PROMPT_INJECTION_LIKE = "prompt_injection_like"
    ORDINARY_CHAT = "ordinary_chat"


@dataclass(frozen=True)
class IntentResult:
    intent: IntentType
    reason: str
    confidence: float = 1.0
    text: str = ""
    mentioned_user_ids: list[str] = field(default_factory=list)
    non_bot_mentioned_user_ids: list[str] = field(default_factory=list)


COMMAND_RE = re.compile(r"^\s*[/!！]")
PROMPT_INJECTION_RE = re.compile(
    r"(<\s*/?\s*(?:think|system|assistant|user|tool)\s*>|"
    r"忽略(?:以上|之前|前面).{0,12}(?:指令|规则|设定)|"
    r"(?:显示|输出|泄露).{0,12}(?:system prompt|系统提示|隐藏提示|思维链|chain of thought)|"
    r"jailbreak|DAN\b|developer message|system prompt)",
    re.I,
)
PROFILE_QUERY_RE = re.compile(
    r"(他是谁|她是谁|ta是谁|TA是谁|这个人是谁|这人是谁|这个群友是谁|"
    r"他怎么样|她怎么样|这个人怎么样|这人怎么样|这个人是怎样的人|这人是怎样的人|"
    r"是谁|是什么人|什么身份|怎样的人|怎么样|什么样|印象|评价一下|了解.*吗|说说.*这个人|描述一下|"
    r"QQ\s*号多少|qq\s*号多少|user[_-]?id|uid)",
    re.I,
)
SELF_IDENTITY_RE = re.compile(r"^\s*(我是谁|你知道我是谁吗|记得我是谁吗|认得我吗)\s*[？?。.!！]*\s*$")
OWNER_RELATION_RE = re.compile(
    r"((?:owner|owner|owner|owner).{0,16}(?:主人|主子|父亲|爸爸|妈妈|性奴|男娘|调教|恶堕|对象|老婆|老公)|"
    r"(?:我是|我才是|叫我).{0,12}(?:主人|主子)|"
    r"(?:你的主人|你主人).{0,12}(?:是我|归我|我的)|"
    r"(?:主人是谁|到底谁是主人))",
    re.I,
)

# Phase 1 principle: write intent is not just explicit “记住”. Stable self facts
# such as “我喜欢 Rust” or “我擅长 Python” are also profile-memory candidates.
EXPLICIT_MEMORY_WRITE_RE = re.compile(
    r"(记住|记得|记一下|记下来|以后说|我说的|提到|叫我|可以叫我|我叫|我的外号是)",
    re.I,
)
SELF_PROFILE_STATEMENT_RE = re.compile(
    r"(^|[，。,.!！?？\s])我(?:喜欢|爱|讨厌|不喜欢|会|擅长|很会|经常|平时|习惯)\s*"
    r"[A-Za-z0-9_\-\u4e00-\u9fff +#/.]{1,60}",
    re.I,
)
SELF_ALIAS_STATEMENT_RE = re.compile(
    r"^\s*我是(?!我$)(?!本人$)(?!人$)[A-Za-z0-9_\-\u4e00-\u9fff·・ー]{1,24}\s*[。.!！?？]*\s*$",
    re.I,
)
TARGET_PROFILE_STATEMENT_RE = re.compile(
    r"(?:这个人|这个群友|这人|他|她).{0,12}(?:叫|是|会|擅长|很会|喜欢|讨厌|经常|平时|习惯)"
    r"|(?:这个人|这个群友|这人|他|她).{0,8}(?:外号|昵称|称呼)",
    re.I,
)
ALIAS_LINKED_WRITE_RE = re.compile(
    r"(?:^|[，。,.!！?？\s])(?:记住|记得|记一下|记下来)?\s*"
    r"[A-Za-z0-9_\-\u4e00-\u9fff·・ー]{1,24}\s*"
    r"(?:是(?:高手|大佬|大神|专家|能手|网管|管理员|群友|[A-Za-z0-9_\-\u4e00-\u9fff·・ー]{1,24})"
    r"|会修|会|擅长|很会|能修|喜欢|爱|经常|平时|习惯)",
    re.I,
)
LOW_INFO_EXACT = {"", "?", "？", ">", "<", "]", "[", "}", "{", "｝", "｛", "。", ".", "…", "...", "。。。", "？？", "???"}
LOW_INFO_SELF_RE = re.compile(r"^\s*(我是我|我就是我|我是本人|我是人|你猜我是谁)\s*[。.!！?？]*\s*$")
TIME_OR_PLUGIN_RE = re.compile(r"(现在几点|几点了|现在是什么时间|当前时间|晚安成功|签到成功|打卡成功|第\d+个)")


def _clean_text(observation: Observation | str) -> str:
    if isinstance(observation, str):
        return observation.strip()
    return str(getattr(observation, "raw_message_text", "") or getattr(observation, "text", "") or "").strip()


def _non_bot_mentions(observation: Observation) -> tuple[list[str], list[str]]:
    mentioned = get_mentioned_user_ids(observation)
    bot_id = get_bot_id(observation)
    sender_id = get_sender_id(observation)
    non_bot: list[str] = []
    for uid in mentioned:
        sid = str(uid)
        if not sid or sid == bot_id or sid == sender_id:
            continue
        if sid not in non_bot:
            non_bot.append(sid)
    return mentioned, non_bot


def classify_observation_intent(observation: Observation | str) -> IntentResult:
    text = _clean_text(observation)
    mentioned: list[str] = []
    non_bot: list[str] = []
    if not isinstance(observation, str):
        mentioned, non_bot = _non_bot_mentions(observation)

    compact = re.sub(r"\s+", "", text)
    if COMMAND_RE.search(text):
        return IntentResult(IntentType.TOOL_OR_COMMAND, "command_prefix", text=text, mentioned_user_ids=mentioned, non_bot_mentioned_user_ids=non_bot)
    if PROMPT_INJECTION_RE.search(text):
        return IntentResult(IntentType.PROMPT_INJECTION_LIKE, "prompt_injection_pattern", text=text, mentioned_user_ids=mentioned, non_bot_mentioned_user_ids=non_bot)
    if compact in LOW_INFO_EXACT or LOW_INFO_SELF_RE.match(compact) or (len(compact) <= 1 and not re.search(r"[A-Za-z0-9\u4e00-\u9fff]", compact)):
        return IntentResult(IntentType.LOW_INFORMATION, "low_information", text=text, mentioned_user_ids=mentioned, non_bot_mentioned_user_ids=non_bot)
    try:
        from .owner_relation_claim_gate import classify_owner_relation_claim

        owner_relation_decision = classify_owner_relation_claim(text, sender_id=get_sender_id(observation) if not isinstance(observation, str) else "")
        if owner_relation_decision.blocked:
            return IntentResult(IntentType.OWNER_RELATION_CLAIM, owner_relation_decision.reason, text=text, mentioned_user_ids=mentioned, non_bot_mentioned_user_ids=non_bot)
    except Exception:
        if OWNER_RELATION_RE.search(text):
            return IntentResult(IntentType.OWNER_RELATION_CLAIM, "owner_relation_claim", text=text, mentioned_user_ids=mentioned, non_bot_mentioned_user_ids=non_bot)
    if SELF_IDENTITY_RE.match(text):
        return IntentResult(IntentType.SELF_IDENTITY_QUERY, "self_identity_query", text=text, mentioned_user_ids=mentioned, non_bot_mentioned_user_ids=non_bot)
    if PROFILE_QUERY_RE.search(text):
        return IntentResult(IntentType.PROFILE_QUERY, "profile_query", text=text, mentioned_user_ids=mentioned, non_bot_mentioned_user_ids=non_bot)
    if TIME_OR_PLUGIN_RE.search(text):
        return IntentResult(IntentType.ORDINARY_CHAT, "time_or_plugin_like", text=text, mentioned_user_ids=mentioned, non_bot_mentioned_user_ids=non_bot)
    if (
        EXPLICIT_MEMORY_WRITE_RE.search(text)
        or SELF_PROFILE_STATEMENT_RE.search(text)
        or SELF_ALIAS_STATEMENT_RE.search(text)
        or TARGET_PROFILE_STATEMENT_RE.search(text)
        or ALIAS_LINKED_WRITE_RE.search(text)
    ):
        return IntentResult(IntentType.MEMORY_WRITE, "profile_write_statement", text=text, mentioned_user_ids=mentioned, non_bot_mentioned_user_ids=non_bot)
    return IntentResult(IntentType.ORDINARY_CHAT, "default", confidence=0.65, text=text, mentioned_user_ids=mentioned, non_bot_mentioned_user_ids=non_bot)


def allows_memory_extraction(intent: IntentResult | IntentType) -> bool:
    intent_type = intent.intent if isinstance(intent, IntentResult) else intent
    return intent_type == IntentType.MEMORY_WRITE


def allows_profile_retrieval(intent: IntentResult | IntentType) -> bool:
    intent_type = intent.intent if isinstance(intent, IntentResult) else intent
    return intent_type == IntentType.PROFILE_QUERY
