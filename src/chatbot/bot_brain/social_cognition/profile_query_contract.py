from __future__ import annotations

import re

from src.chatbot.bot_brain.natural_output import strip_source_prefix, guard_natural_output_reply

from src.chatbot.bot_brain.models import Observation

CONTRACT_MARKER = "自然回忆回答要求"

AMBIGUOUS_OR_SELF_INTRO_RE = re.compile(
    r"(你说的是谁|你问的是谁|范围有点大|具体指哪个|告诉我具体|我才好翻|"
    r"我是Bot|我是Bot|我是Bot|我是Bot|放课后网络观测部|"
    r"你是想问.*还是.*我|如果是后者的话)",
    re.I | re.S,
)


def has_profile_query_contract(context: str | None) -> bool:
    return CONTRACT_MARKER in (context or "")


def is_bad_profile_query_reply(reply: str | None) -> bool:
    text = str(reply or "").strip()
    if not text:
        return True
    return bool(AMBIGUOUS_OR_SELF_INTRO_RE.search(text))


def profile_query_answer_contract(
    *,
    target_user_id: str,
    hard_mention_target: bool,
    wants_public_qq: bool = False,
) -> str:
    """Persona-facing guidance for a resolved profile query.

    This is deliberately not a database/protocol dump. It steers generation while
    remaining safe if included in prompt context.
    """
    if hard_mention_target:
        resolved_hint = "这次问题已经指向刚才被提到的那个人。"
    else:
        resolved_hint = "这次问题已经指向一个明确的人。"
    qq_hint = "如果对方是在问账号，可以回答这个已解析目标的 账号 ID。" if wants_public_qq else "没有问账号时，只聊你记得的称呼和印象。"
    return (
        f"{CONTRACT_MARKER}：{resolved_hint}"
        "先说已经想起来的称呼或印象，不要反问是谁，也不要切成自我介绍。"
        "信息少就自然说还不太熟；不知道的现实身份不要编。"
        f"{qq_hint}"
    )


def extract_profile_query_contract_block(text: str | None) -> str:
    source = str(text or "")
    idx = source.find(CONTRACT_MARKER)
    if idx < 0:
        return ""
    return source[idx:].strip()[:1800]


def _strip_prefix(line: str) -> str:
    return strip_source_prefix(line)


def reliable_memory_sentences(social_context: str | None) -> list[str]:
    sentences: list[str] = []
    for raw in str(social_context or "").splitlines():
        line = raw.strip()
        if not line.startswith("-"):
            continue
        if "目标群友 账号ID" in line:
            continue
        if "：" not in line:
            continue
        sentence = _strip_prefix(line)
        if not sentence:
            continue
        if sentence not in sentences:
            sentences.append(sentence)
    return sentences


def fallback_profile_query_answer(social_context: str | None, *, max_length: int = 240) -> str:
    memories = reliable_memory_sentences(social_context)
    if memories:
        known = "；".join(memories[:3])
        reply = f"我想起来一点：{known}。其他细节我还不太熟，不敢乱说。"
    else:
        reply = "我现在还没想起足够稳定的印象，不敢乱编。"
    return reply[:max_length].rstrip()


def guard_profile_query_reply(reply: str, social_context: str | None, *, max_length: int = 240) -> str:
    if not has_profile_query_contract(social_context):
        return reply
    if not is_bad_profile_query_reply(reply):
        return reply
    return fallback_profile_query_answer(social_context, max_length=max_length)
