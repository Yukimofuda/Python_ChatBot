from __future__ import annotations

from functools import lru_cache
import logging
from pathlib import Path
import re

from src.chatbot.shion_brain.context import GenerationContext, build_generation_context, context_to_messages
from src.chatbot.shion_brain.critic import FAILURE_REPLY, Critic
from src.chatbot.shion_brain.llm_provider import LLMProvider, LLMProviderError, resolve_llm_config
from src.chatbot.shion_brain.models import Decision, Memory, MoodState, Observation
from src.chatbot.shion_brain.thought_queue import Thought


logger = logging.getLogger(__name__)
PROMPT_DIR = Path(__file__).with_name("prompts")
PROJECT_ROOT = Path(__file__).resolve().parents[3]
NATURAL_BOUNDARIES = ("。", "？", "！", "\n", "…", ".", "?", "!")


class EmptyLLMResponseError(RuntimeError):
    pass


class BadLLMReplyError(RuntimeError):
    pass


@lru_cache(maxsize=8)
def load_prompt(name: str) -> str:
    path = PROMPT_DIR / name
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


@lru_cache(maxsize=1)
def load_character_prompt() -> str:
    path = PROJECT_ROOT / "character_prompt.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


class ReplyGenerator:
    def __init__(self, provider: LLMProvider | None = None, critic: Critic | None = None) -> None:
        self.provider = provider or LLMProvider()
        self.critic = critic or Critic()

    async def generate(
        self,
        observation: Observation,
        mood: MoodState,
        memories: list[Memory],
        decision: Decision,
        *,
        entry: str = "brain",
        self_state_summary: str = "",
        pending_thoughts: list[Thought] | None = None,
        safety_notes: str = "",
    ) -> str:
        context = build_generation_context(
            observation=observation,
            decision=decision,
            mood=mood,
            memories=memories,
            self_state_summary=self_state_summary,
            pending_thoughts=pending_thoughts or [],
            safety_notes=safety_notes,
        )
        return await self.safe_generate_reply(context, entry=entry)

    async def safe_generate_reply(
        self,
        context: GenerationContext,
        *,
        entry: str,
    ) -> str:
        messages = build_messages(context)
        config = resolve_llm_config()
        try:
            content, fallback = await self.provider.complete(messages, temperature=context.decision.temperature)
            if fallback or not content or not content.strip():
                raise EmptyLLMResponseError("Gemini returned empty content")
            reply = clean_reply(content, max_length=context.decision.max_length)
            verdict = self.critic.check(reply, decision=context.decision)
            if not verdict.ok:
                raise BadLLMReplyError(verdict.reason or "reply rejected")
            return verdict.text
        except Exception as exc:
            status_code = exc.status_code if isinstance(exc, LLMProviderError) else None
            response_body = exc.response_body if isinstance(exc, LLMProviderError) else ""
            retry_after = exc.retry_after_seconds if isinstance(exc, LLMProviderError) else None
            logger.exception(
                "Gemini generation failed | provider=%s model=%s status=%s retry_after=%s entry=%s user_input=%r gemini_error=%r",
                config.provider,
                config.model,
                status_code,
                retry_after,
                entry,
                context.observation.text[:500],
                response_body[:1000],
            )
            return FAILURE_REPLY


def clean_reply(text: str, *, max_length: int) -> str:
    clean = str(text).replace("\r\n", "\n").replace("\r", "\n").strip()
    clean = re.sub(r"```(?:text|markdown)?\s*", "", clean).replace("```", "").strip()
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    if len(clean) <= max_length:
        return _repair_dangling_kaomoji(clean)
    return natural_truncate(clean, max_length)


def natural_truncate(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return _repair_dangling_kaomoji(text.strip())
    window = text[:max_length].rstrip()
    best = -1
    min_pos = min(20, max(1, int(max_length * 0.45)))
    for mark in NATURAL_BOUNDARIES:
        pos = window.rfind(mark)
        if pos >= min_pos:
            best = max(best, pos + len(mark))
    if best > 0:
        return _repair_dangling_kaomoji(window[:best].strip())
    for sep in ("，", "、", ";", "；", " "):
        pos = window.rfind(sep)
        if pos >= min_pos:
            return _repair_dangling_kaomoji(window[:pos].strip() + "…")
    return _repair_dangling_kaomoji(window.rstrip("，、；;：:") + "…")


def _repair_dangling_kaomoji(text: str) -> str:
    clean = text.strip()
    last_open = max(clean.rfind("("), clean.rfind("（"))
    last_close = max(clean.rfind(")"), clean.rfind("）"))
    if last_open > last_close and len(clean) - last_open <= 14:
        clean = clean[:last_open].rstrip()
    return clean


def _time_hint() -> str:
    from datetime import datetime

    hour = datetime.now().hour
    if 5 <= hour < 11:
        return "现在偏早，语气可以清醒一点、轻快一点。"
    if 11 <= hour < 15:
        return "现在接近中午或午后，语气自然、简短，不要编造现实午饭经历。"
    if 18 <= hour < 24:
        return "现在是晚上，语气可以更安静、有陪伴感，但不要说教。"
    return "现在偏深夜，语气放轻；必要时提醒休息，但不要像家长。"


def build_messages(context: GenerationContext) -> list[dict[str, str]]:
    return context_to_messages(
        context,
        character_prompt=load_character_prompt(),
        base_persona=load_prompt("base_persona.md"),
        style_guide=load_prompt("style_guide.md"),
        reply_guide=load_prompt("reply_generation.md"),
    )
