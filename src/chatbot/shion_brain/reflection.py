from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from src.chatbot.shion_brain.memory_store import SQLiteMemoryStore, new_memory
from src.chatbot.shion_brain.models import (
    BeliefHypothesis,
    DistilledMemory,
    ProceduralPrompt,
    SemanticEdge,
    new_id,
    utc_now_iso,
)

logger = logging.getLogger(__name__)

SENSITIVE_PATTERNS = [
    re.compile(r"" + "sk" + r"-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"" + "AI" + "za" + r"[0-9A-Za-z_\-]{12,}"),
    re.compile(r"(?i)(api[_-]?key|token|password|passwd|cookie|authorization)\s*[:=]\s*\S+"),
]


class ReflectionEngine:
    def __init__(self, store: SQLiteMemoryStore) -> None:
        self.store = store

    async def reflect_group(self, group_id: str) -> str:
        recent = await self.store.recent(group_id, limit=80)
        if not recent:
            return "最近没有足够消息生成反思。"
        words = Counter()
        for memory in recent:
            for token in memory.content.replace("，", " ").replace("。", " ").split():
                if len(token) >= 2:
                    words[token] += 1
        top = "、".join(word for word, _ in words.most_common(8)) or "暂无"
        summary = f"群聊反思：最近消息 {len(recent)} 条；高频词：{top}。"
        await self.store.add_memory(new_memory(group_id, "reflection", summary, ["reflection"], 0.7))
        return summary


@dataclass(slots=True)
class ReflectionInput:
    scope_id: str
    recent_observations: list[dict[str, Any]]
    recent_replies: list[dict[str, Any]]
    pending_thoughts: list[dict[str, Any]]
    previous_prediction: str | None = None
    user_feedback_signals: list[str] | None = None


@dataclass(slots=True)
class ReflectionOutput:
    prospective_prediction: str
    retrospective_note: str
    surprise_score: float
    semantic_candidates: list[dict[str, Any]]
    belief_candidates: list[dict[str, Any]]
    procedural_candidates: list[dict[str, Any]]
    stale_memory_ids: list[str]
    summary: str


class AdaptiveReflectionEngine:
    def __init__(
        self,
        *,
        memory_store: SQLiteMemoryStore,
        llm_provider=None,
        thought_queue=None,
        max_recent_observations: int = 60,
        max_prompt_chars: int = 6000,
    ) -> None:
        self.memory_store = memory_store
        self.llm_provider = llm_provider
        self.thought_queue = thought_queue
        self.max_recent_observations = max_recent_observations
        self.max_prompt_chars = max_prompt_chars
        self._lock = asyncio.Lock()

    async def run_cycle(self, scope_id: str) -> DistilledMemory | None:
        if self._lock.locked():
            logger.info("Reflection cycle skipped: previous cycle still running")
            return None
        async with self._lock:
            try:
                await self.memory_store.init_cognitive_schema()
                reflection_input = await self._build_input(scope_id)
                output = await self._reflect(reflection_input)
                distilled = self._convert_output(scope_id, output)
                await self.memory_store.save_distillation_result(distilled)
                if distilled.stale_memory_ids:
                    await self.memory_store.deactivate_stale_semantic_edges(
                        scope_id=scope_id,
                        memory_ids=distilled.stale_memory_ids,
                    )
                await self._mark_consumed_thoughts(scope_id)
                return distilled
            except Exception:
                logger.exception("Adaptive reflection cycle failed")
                return None

    async def _build_input(self, scope_id: str) -> ReflectionInput:
        recent_observations: list[dict[str, Any]] = []
        recent_replies: list[dict[str, Any]] = []
        pending_thoughts: list[dict[str, Any]] = []
        try:
            recent = await self.memory_store.recent(scope_id, limit=self.max_recent_observations)
            recent_observations = [
                {
                    "id": memory.id,
                    "text": redact_sensitive(memory.content),
                    "timestamp": memory.created_at,
                    "tags": memory.tags,
                }
                for memory in recent
            ]
        except Exception:
            logger.exception("Failed to load recent observations for reflection")
        try:
            if self.thought_queue and hasattr(self.thought_queue, "list_pending_thoughts"):
                thoughts = await self.thought_queue.list_pending_thoughts(scope_id=scope_id, limit=12)
                pending_thoughts = [
                    t if isinstance(t, dict) else getattr(t, "__dict__", {"content": str(t)})
                    for t in thoughts
                ]
        except Exception:
            logger.exception("Failed to load pending thoughts for reflection")
        return ReflectionInput(
            scope_id=scope_id,
            recent_observations=recent_observations,
            recent_replies=recent_replies,
            pending_thoughts=pending_thoughts,
            previous_prediction=None,
            user_feedback_signals=self._extract_feedback_signals(recent_observations),
        )

    def _extract_feedback_signals(self, observations: list[dict[str, Any]]) -> list[str]:
        signals: list[str] = []
        confusion_words = ("？", "?", "没懂", "什么鬼", "啥意思", "不对", "不是")
        praise_words = ("谢谢", "厉害", "好用", "懂了", "可以", "牛")
        for obs in observations[-20:]:
            text = str(obs.get("text") or obs.get("content") or "")
            if any(word in text for word in confusion_words):
                signals.append(f"confusion:{redact_sensitive(text)[:80]}")
            elif any(word in text for word in praise_words):
                signals.append(f"positive:{redact_sensitive(text)[:80]}")
        return signals[-8:]

    async def _reflect(self, data: ReflectionInput) -> ReflectionOutput:
        if self.llm_provider:
            try:
                return await self._llm_reflect(data)
            except Exception:
                logger.exception("LLM reflection failed; falling back to rule reflection")
        return self._rule_reflect(data)

    async def _llm_reflect(self, data: ReflectionInput) -> ReflectionOutput:
        prompt = self._build_reflection_prompt(data)
        raw = await self._call_llm_json(prompt)
        return self._normalize_output(self._safe_parse_json(raw))

    async def _call_llm_json(self, prompt: str) -> str:
        messages = [
            {
                "role": "system",
                "content": "你是 Shion 的后台反思与记忆蒸馏模块。只输出 JSON，不输出解释，不保存敏感信息。",
            },
            {"role": "user", "content": prompt},
        ]
        provider = self.llm_provider
        if hasattr(provider, "complete"):
            result = await provider.complete(messages, temperature=0.25)
            if isinstance(result, tuple):
                return str(result[0])
            return str(result)
        if hasattr(provider, "chat"):
            return str(await provider.chat(messages))
        if hasattr(provider, "generate"):
            return str(await provider.generate(messages))
        raise RuntimeError("Unsupported llm_provider interface")

    def _build_reflection_prompt(self, data: ReflectionInput) -> str:
        observations = [
            {
                "text": redact_sensitive(str(obs.get("text") or obs.get("content") or ""))[:300],
                "timestamp": str(obs.get("timestamp", ""))[:64],
                "tags": obs.get("tags", []),
            }
            for obs in data.recent_observations[-self.max_recent_observations :]
        ]
        thoughts = [
            {
                "type": str(thought.get("type", ""))[:32],
                "content": redact_sensitive(str(thought.get("content", "")))[:200],
                "priority": thought.get("priority", 0),
            }
            for thought in data.pending_thoughts[-12:]
        ]
        payload = json.dumps(
            {
                "scope_id": data.scope_id,
                "recent_observations": observations,
                "pending_thoughts": thoughts,
                "feedback_signals": data.user_feedback_signals or [],
            },
            ensure_ascii=False,
        )[: self.max_prompt_chars]
        return f"""
请对以下近期互动做一次 Shion 后台记忆蒸馏。只输出 JSON。

目标：
1. Prospective Reflection：预测接下来用户/群可能真正需要什么。
2. Retrospective Reflection：判断 Shion 之前是否理解偏差，给出 surprise_score。
3. Consolidation：只保留有长期价值的语义记忆、信念假设、行为记忆。
4. 过滤日常废话、重复闲聊、敏感信息。
5. 不要保存 token、API key、密码、cookie、身份证、手机号。
6. 对不确定内容用低 confidence/probability，不要写成事实。

输入：
{payload}

输出 JSON 字段：prospective_prediction, retrospective_note, surprise_score,
semantic_candidates, belief_candidates, procedural_candidates, stale_memory_ids, summary。
"""

    def _safe_parse_json(self, raw: str) -> dict[str, Any]:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?", "", raw).strip()
            raw = re.sub(r"```$", "", raw).strip()
        try:
            return json.loads(raw)
        except Exception:
            logger.warning("Failed to parse reflection JSON: %s", raw[:500])
            return {}

    def _normalize_output(self, obj: dict[str, Any]) -> ReflectionOutput:
        return ReflectionOutput(
            prospective_prediction=str(obj.get("prospective_prediction") or "")[:800],
            retrospective_note=str(obj.get("retrospective_note") or "")[:800],
            surprise_score=_clamp(float(obj.get("surprise_score") or 0.0)),
            semantic_candidates=list(obj.get("semantic_candidates") or [])[:12],
            belief_candidates=list(obj.get("belief_candidates") or [])[:8],
            procedural_candidates=list(obj.get("procedural_candidates") or [])[:8],
            stale_memory_ids=[str(item) for item in (obj.get("stale_memory_ids") or [])][:30],
            summary=str(obj.get("summary") or "")[:600],
        )

    def _rule_reflect(self, data: ReflectionInput) -> ReflectionOutput:
        feedback = data.user_feedback_signals or []
        surprise = 0.0
        if any(signal.startswith("confusion:") for signal in feedback):
            surprise += 0.55
        if any(signal.startswith("positive:") for signal in feedback):
            surprise += 0.15
        recent_text = " ".join(redact_sensitive(str(obs.get("text") or obs.get("content") or "")) for obs in data.recent_observations[-10:])
        semantic: list[dict[str, Any]] = []
        procedural: list[dict[str, Any]] = []
        if "少用 emoji" in recent_text or "别用 emoji" in recent_text:
            semantic.append(
                {
                    "subject": "style:group",
                    "relation": "prefers_style",
                    "object_value": "少用 emoji，回复更直接",
                    "object_type": "preference",
                    "confidence": 0.65,
                    "tags": ["style", "preference"],
                    "conflict_group": "style_emoji_usage",
                }
            )
            procedural.append(
                {
                    "user_id": None,
                    "context_signature": "general_reply",
                    "style_hint": "less_emoji",
                    "prompt_delta": "减少 emoji，避免卖萌过度，直接回答。",
                    "last_outcome": "success",
                    "tags": ["style"],
                }
            )
        if any(signal.startswith("confusion:") for signal in feedback):
            procedural.append(
                {
                    "user_id": None,
                    "context_signature": "repair_after_confusion",
                    "style_hint": "more_direct",
                    "prompt_delta": "用户困惑时，不要继续玩梗；先用更短、更直接的方式重说一遍。",
                    "last_outcome": "failure",
                    "tags": ["repair", "clarity"],
                }
            )
        return ReflectionOutput(
            prospective_prediction="用户可能需要更清楚、更少模板化的回应。",
            retrospective_note="近期出现困惑或修正信号，应降低玩梗比例，提高直接解释。",
            surprise_score=_clamp(surprise),
            semantic_candidates=semantic,
            belief_candidates=[],
            procedural_candidates=procedural,
            stale_memory_ids=[],
            summary="规则反思完成：更新少量风格和修正策略。",
        )

    def _convert_output(self, scope_id: str, out: ReflectionOutput) -> DistilledMemory:
        now = utc_now_iso()
        semantic_edges: list[SemanticEdge] = []
        beliefs: list[BeliefHypothesis] = []
        procedural: list[ProceduralPrompt] = []
        for item in out.semantic_candidates:
            try:
                subject = str(item.get("subject") or "")[:160]
                relation = str(item.get("relation") or "")[:80]
                obj = str(item.get("object_value") or "")[:500]
                if not subject or not relation or not obj or has_sensitive(obj):
                    continue
                semantic_edges.append(
                    SemanticEdge(
                        id=new_id("sem"),
                        scope="group",
                        scope_id=scope_id,
                        subject=subject,
                        relation=relation,
                        object_value=obj,
                        object_type=str(item.get("object_type") or "attribute"),
                        confidence=_clamp(float(item.get("confidence") or 0.5)),
                        evidence_refs=[],
                        tags=[str(tag)[:40] for tag in item.get("tags", [])][:8],
                        conflict_group=item.get("conflict_group"),
                        created_at=now,
                        updated_at=now,
                    )
                )
            except Exception:
                logger.exception("Bad semantic candidate skipped")
        for item in out.belief_candidates:
            try:
                hypothesis = str(item.get("hypothesis") or "")[:500]
                if not hypothesis or has_sensitive(hypothesis):
                    continue
                beliefs.append(
                    BeliefHypothesis(
                        id=new_id("belief"),
                        scope_id=scope_id,
                        subject=str(item.get("subject") or "group")[:160],
                        hypothesis=hypothesis,
                        probability=_clamp(float(item.get("probability") or 0.5)),
                        evidence_refs=[],
                        uncertainty_note=str(item.get("uncertainty_note") or "")[:300],
                        updated_at=now,
                    )
                )
            except Exception:
                logger.exception("Bad belief candidate skipped")
        for item in out.procedural_candidates:
            try:
                delta = str(item.get("prompt_delta") or "")[:500]
                if not delta or has_sensitive(delta):
                    continue
                procedural.append(
                    ProceduralPrompt(
                        id=new_id("proc"),
                        scope_id=scope_id,
                        user_id=item.get("user_id"),
                        context_signature=str(item.get("context_signature") or "general")[:120],
                        style_hint=str(item.get("style_hint") or "general")[:120],
                        prompt_delta=delta,
                        last_outcome=str(item.get("last_outcome") or "neutral"),
                        tags=[str(tag)[:40] for tag in item.get("tags", [])][:8],
                        evidence_count=1,
                        created_at=now,
                        updated_at=now,
                    )
                )
            except Exception:
                logger.exception("Bad procedural candidate skipped")
        return DistilledMemory(
            id=new_id("distill"),
            scope_id=scope_id,
            reflection_type="consolidation",
            summary=out.summary or out.retrospective_note or "reflection completed",
            semantic_edges=semantic_edges,
            belief_updates=beliefs,
            procedural_updates=procedural,
            stale_memory_ids=out.stale_memory_ids,
            surprise_score=out.surprise_score,
            created_at=now,
        )

    async def _mark_consumed_thoughts(self, scope_id: str) -> None:
        if not self.thought_queue:
            return
        try:
            if hasattr(self.thought_queue, "mark_reflection_consumed"):
                await self.thought_queue.mark_reflection_consumed(scope_id)
        except Exception:
            logger.exception("Failed to mark consumed thoughts")


def redact_sensitive(text: str) -> str:
    redacted = text or ""
    for pattern in SENSITIVE_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def has_sensitive(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in SENSITIVE_PATTERNS)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
