from __future__ import annotations

from src.chatbot.bot_brain.types import BrainObservation, ReplyPlan


QUESTION_MARKERS = {"?", "？", "how", "what", "why", "怎么", "啥", "什么"}


def plan_reply(observation: BrainObservation) -> ReplyPlan:
    lowered = observation.normalized_text.lower()
    asks_question = any(token in lowered for token in QUESTION_MARKERS)
    if not observation.normalized_text:
        return ReplyPlan(intent="empty", requires_fallback=True)
    if asks_question:
        return ReplyPlan(intent="answer", max_length=180)
    return ReplyPlan(intent="ack", max_length=120)
