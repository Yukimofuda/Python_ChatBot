from __future__ import annotations

import re

from src.chatbot.bot_brain.types import BrainObservation


WORD_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9_]+")


def normalize_observation(text: str, *, scope: str = "demo") -> BrainObservation:
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    tokens = tuple(token.lower() for token in WORD_RE.findall(normalized))
    return BrainObservation(text=text, normalized_text=normalized, tokens=tokens, scope=scope)
