from __future__ import annotations

import re

from src.chatbot.bot_brain.types import BrainReply, CriticResult


FORBIDDEN_RE = re.compile(
    "|".join(
        [
            "per" "sona",
            "char" "acter",
            "role" "play",
            "ow" "ner",
            "social_" "cognition",
            "shi" "on",
            "nan" "ase",
            "\u4e03\u702c",
            "\u6801\u97f3",
            "qq号",
            "user_" "id",
            "group_" "id",
        ]
    ),
    re.I,
)


def review_reply(reply: BrainReply) -> CriticResult:
    reasons: list[str] = []
    if not reply.text.strip():
        reasons.append("empty_reply")
    if FORBIDDEN_RE.search(reply.text):
        reasons.append("forbidden_term")
    return CriticResult(ok=not reasons, reasons=tuple(reasons))
