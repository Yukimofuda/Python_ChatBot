from __future__ import annotations

from dataclasses import dataclass
import logging
import math
import random
import re
import time

from src.chatbot.settings import get_settings
from src.chatbot.shion_brain.critic import FAILURE_REPLY, SENSITIVE_BLOCK_REPLY, Critic
from src.chatbot.shion_brain.generator import ReplyGenerator
from src.chatbot.shion_brain.memory_store import SQLiteMemoryStore
from src.chatbot.shion_brain.models import AgendaItem, CognitiveDecisionPatch, Decision, Memory, Observation, new_id, utc_now
from src.chatbot.shion_brain.mood_engine import MoodEngine
from src.chatbot.shion_brain.persona_engine import PersonaEngine
from src.chatbot.shion_brain.retrieval import Retriever
from src.chatbot.shion_brain.self_state import SelfStateStore, render_self_state_for_prompt
from src.chatbot.shion_brain.thought_queue import Thought, ThoughtQueue


LEVEL_SECONDS = {"low": 1800, "medium": 600, "high": 180}
LEVEL_PROBABILITY = {"low": 0.08, "medium": 0.16, "high": 0.25}
logger = logging.getLogger(__name__)
CONFUSION_RE = re.compile(r"^(\?|？|什么鬼|没懂|你在说什么|啊\?|哈\?|啥|啥意思)$")


@dataclass
class ReplyStatus:
    status: str
    reason: str
    user_message: str
    bot_reply: str
    timestamp: float




@dataclass(slots=True)
class PlannerSignals:
    mentions_bot: bool = False
    is_command: bool = False
    asks_question: bool = False
    asks_opinion: bool = False
    confusion: bool = False
    distress: bool = False
    tech_bottleneck: bool = False
    logical_conflict: bool = False
    complex_group_discussion: bool = False
    sensitive: bool = False
    recent_failed_reply: bool = False
    pending_repair_thought: bool = False
    relationship_familiarity: float = 0.0
    self_energy: float = 0.7
    self_stress: float = 0.2
    group_activity_level: float = 0.5


class MotivationPlanner:
    def __init__(
        self,
        *,
        thought_queue=None,
        semantic_store=None,
        min_auto_reply_score: float = 0.72,
        min_deep_score: float = 0.82,
    ) -> None:
        self.thought_queue = thought_queue
        self.semantic_store = semantic_store
        self.min_auto_reply_score = min_auto_reply_score
        self.min_deep_score = min_deep_score

    async def decide_cognitive_patch(
        self,
        *,
        observation,
        base_decision=None,
        self_state=None,
        relationship=None,
        pending_thoughts: list | None = None,
        retrieved_memories: list | None = None,
        cooldown_ok: bool = True,
        ambient_enabled: bool = True,
    ) -> CognitiveDecisionPatch:
        try:
            signals = self._extract_signals(
                observation=observation,
                self_state=self_state,
                relationship=relationship,
                pending_thoughts=pending_thoughts or [],
                retrieved_memories=retrieved_memories or [],
            )
            gate = self._rule_gate(signals, cooldown_ok=cooldown_ok, ambient_enabled=ambient_enabled)
            if gate.reply_intent == "stay_silent" and not signals.mentions_bot:
                return gate
            motivation = self._score_motivation(signals)
            meta = self._score_meta_motivation(signals)
            intent = self._select_intent(signals, motivation, meta)
            patch = CognitiveDecisionPatch(
                motivation_score=motivation,
                meta_motivation_score=meta,
                reply_intent=intent,
                allowed_actions=self._allowed_actions(intent),
            )
            if meta >= self.min_deep_score and intent in {"inspire", "challenge", "synthesize", "repair"}:
                patch.incubation_required = self._should_incubate(signals)
                patch.incubation_reason = self._incubation_reason(signals, intent)
                patch.internal_notes.append("deep_motivation_detected")
                if patch.incubation_required:
                    await self._create_incubation_thought(observation, patch)
            if not signals.mentions_bot and motivation < self.min_auto_reply_score and meta < self.min_deep_score:
                patch.reply_intent = "stay_silent"
                patch.allowed_actions = []
                patch.internal_notes.append("motivation_below_auto_reply_threshold")
            if signals.mentions_bot and patch.reply_intent == "stay_silent":
                patch.reply_intent = "answer"
                patch.allowed_actions = ["reply"]
            return patch
        except Exception:
            return CognitiveDecisionPatch(
                motivation_score=0.5,
                reply_intent="answer",
                internal_notes=["planner_exception_fallback"],
                allowed_actions=["reply"],
            )

    def _extract_signals(self, *, observation, self_state, relationship, pending_thoughts: list, retrieved_memories: list) -> PlannerSignals:
        text = self._get_text(observation)
        features = getattr(observation, "features", {}) or {}
        if not isinstance(features, dict):
            features = {}
        lower = text.lower()
        confusion_words = ("？", "?", "没懂", "什么鬼", "啥意思", "不对", "不是这个", "看不懂")
        distress_words = ("救命", "完了", "寄了", "崩溃", "焦虑", "难受", "不想学", "写不完")
        opinion_words = ("怎么看", "你觉得", "评价", "锐评", "有没有可能", "是否")
        tech_words = ("报错", "traceback", "exception", "error", "nonebot", "napcat", "websocket", "sqlite", "gemini", "python", "ffmpeg", "yt-dlp", "api", "端口", "配置")
        logic_words = ("矛盾", "不合理", "逻辑", "证明", "为什么", "反例", "悖论")
        synth_words = ("总结一下", "整理一下", "归纳", "这段讨论", "大家刚才")
        pending_repair = any(self._thought_contains(thought, ("repair", "没解释清楚", "失败", "修正")) for thought in pending_thoughts)
        return PlannerSignals(
            mentions_bot=bool(getattr(observation, "mentions_bot", False) or features.get("mentions_bot") or features.get("name_trigger")),
            is_command=bool(getattr(observation, "is_command", False) or features.get("is_command")),
            asks_question=bool(features.get("is_question") or "?" in text or "？" in text),
            asks_opinion=any(word in text for word in opinion_words),
            confusion=any(word in text for word in confusion_words),
            distress=any(word in text for word in distress_words),
            tech_bottleneck=any(word in lower for word in tech_words) or bool(features.get("technical_help")),
            logical_conflict=any(word in text for word in logic_words),
            complex_group_discussion=any(word in text for word in synth_words) or len(retrieved_memories) >= 8,
            sensitive=bool(features.get("sensitive") or features.get("has_sensitive")),
            recent_failed_reply=bool(features.get("recent_failed_reply")),
            pending_repair_thought=pending_repair,
            relationship_familiarity=float(getattr(relationship, "familiarity", 0.0) or 0.0),
            self_energy=float(getattr(self_state, "energy", 0.7) or 0.7),
            self_stress=float(getattr(self_state, "stress", 0.2) or 0.2),
            group_activity_level=float(features.get("group_activity_level", 0.5) or 0.5),
        )

    def _rule_gate(self, signals: PlannerSignals, *, cooldown_ok: bool, ambient_enabled: bool) -> CognitiveDecisionPatch:
        if signals.is_command:
            return CognitiveDecisionPatch(reply_intent="stay_silent", internal_notes=["rule_gate: command"])
        if signals.sensitive:
            return CognitiveDecisionPatch(motivation_score=0.2, meta_motivation_score=0.9, reply_intent="ask_clarification", internal_notes=["rule_gate: sensitive_content"], allowed_actions=["reply_safely"])
        if not ambient_enabled and not signals.mentions_bot:
            return CognitiveDecisionPatch(reply_intent="stay_silent", internal_notes=["rule_gate: ambient_disabled"])
        if not cooldown_ok and not signals.mentions_bot:
            return CognitiveDecisionPatch(reply_intent="stay_silent", internal_notes=["rule_gate: cooldown"])
        return CognitiveDecisionPatch(motivation_score=0.1, reply_intent="answer", internal_notes=["rule_gate: pass"], allowed_actions=["reply"])

    def _score_motivation(self, signals: PlannerSignals) -> float:
        score = 0.0
        if signals.mentions_bot:
            score += 0.65
        if signals.asks_question:
            score += 0.22
        if signals.asks_opinion:
            score += 0.25
        if signals.confusion:
            score += 0.35
        if signals.distress:
            score += 0.38
        if signals.tech_bottleneck:
            score += 0.32
        if signals.pending_repair_thought:
            score += 0.30
        if signals.recent_failed_reply:
            score += 0.25
        if signals.complex_group_discussion:
            score += 0.28
        if signals.logical_conflict:
            score += 0.22
        score += min(0.12, max(0.0, signals.relationship_familiarity) * 0.12)
        if not signals.mentions_bot and not signals.distress and not signals.tech_bottleneck:
            score *= 0.75 + 0.25 * max(0.0, min(1.0, signals.self_energy))
        if signals.self_stress > 0.65 and not signals.confusion:
            score *= 0.9
        return self._squash(score)

    def _score_meta_motivation(self, signals: PlannerSignals) -> float:
        raw = 0.0
        if signals.confusion:
            raw += 0.78
        if signals.distress:
            raw += 0.92
        if signals.tech_bottleneck:
            raw += 0.70
        if signals.logical_conflict:
            raw += 0.66
        if signals.complex_group_discussion:
            raw += 0.76
        if signals.pending_repair_thought:
            raw += 0.55
        if signals.asks_opinion:
            raw += 0.32
        return self._squash(raw)

    def _select_intent(self, signals: PlannerSignals, motivation: float, meta: float) -> str:
        if signals.sensitive:
            return "ask_clarification"
        if signals.confusion or signals.pending_repair_thought or signals.recent_failed_reply:
            return "repair"
        if signals.complex_group_discussion:
            return "synthesize"
        if signals.logical_conflict and (signals.asks_opinion or signals.asks_question):
            return "challenge"
        if signals.distress:
            return "inspire" if meta >= 0.75 else "comfort"
        if signals.tech_bottleneck:
            return "answer" if signals.asks_question else "ask_clarification"
        if signals.asks_opinion and meta >= 0.7:
            return "challenge"
        if signals.asks_question or signals.mentions_bot:
            return "answer"
        if motivation >= 0.75 and signals.self_stress < 0.6:
            return "tease"
        return "stay_silent"

    def _allowed_actions(self, intent: str) -> list[str]:
        return {
            "stay_silent": [],
            "answer": ["reply"],
            "comfort": ["reply"],
            "tease": ["reply_lightly"],
            "ask_clarification": ["reply"],
            "repair": ["reply", "mark_repair_done"],
            "remember": ["reply", "write_memory"],
            "inspire": ["reply", "create_reflection_thought"],
            "challenge": ["reply", "create_reflection_thought"],
            "synthesize": ["reply", "summarize_context"],
        }.get(intent, ["reply"])

    def _should_incubate(self, signals: PlannerSignals) -> bool:
        if signals.mentions_bot or signals.distress:
            return False
        return signals.complex_group_discussion or signals.logical_conflict

    def _incubation_reason(self, signals: PlannerSignals, intent: str) -> str:
        if intent == "synthesize":
            return "群内讨论较复杂，需要先整理上下文。"
        if intent == "challenge":
            return "检测到可能的逻辑冲突，需要谨慎形成质疑。"
        if intent == "inspire":
            return "用户可能需要启发式回应，而非普通玩笑。"
        return "高阶动机需要后台孵化。"

    async def _create_incubation_thought(self, observation, patch: CognitiveDecisionPatch) -> None:
        if not self.thought_queue or not hasattr(self.thought_queue, "create_thought"):
            return
        await self.thought_queue.create_thought(
            scope_id=self._get_scope_id(observation),
            user_id=self._get_user_id(observation),
            type="reflection",
            content=f"Incubate reply intent={patch.reply_intent}: {patch.incubation_reason}",
            priority=0.75 + patch.meta_motivation_score * 0.2,
            source_observation_id=str(getattr(observation, "id", "")),
            status="incubating",
        )

    def _get_text(self, observation) -> str:
        return str(getattr(observation, "text", None) or getattr(observation, "content", None) or "")

    def _get_scope_id(self, observation) -> str:
        return str(getattr(observation, "group_id", None) or getattr(observation, "scope_id", None) or "global")

    def _get_user_id(self, observation) -> str | None:
        value = getattr(observation, "user_id", None)
        return str(value) if value is not None else None

    def _thought_contains(self, thought, needles: tuple[str, ...]) -> bool:
        text = str(getattr(thought, "content", None) or (thought.get("content") if isinstance(thought, dict) else "") or "")
        typ = str(getattr(thought, "type", None) or (thought.get("type") if isinstance(thought, dict) else "") or "")
        return any(needle in text or needle in typ for needle in needles)

    def _squash(self, value: float) -> float:
        return max(0.0, min(1.0, 1.0 - math.exp(-max(0.0, value))))


class Planner:
    def __init__(self) -> None:
        self._cooldowns: dict[str, float] = {}

    def decide(self, observation: Observation, memories: list[Memory]) -> Decision:
        settings = get_settings()
        if observation.is_command:
            return Decision(False, "none", "command message", 0, 0.0, [], "normal")
        if observation.features.get("has_sensitive"):
            return Decision(True, "safety", "sensitive text", 120, 0.2, [], "strict")
        memory_ids = [memory.id for memory in memories[:6]]
        if observation.mentions_bot:
            return Decision(True, "direct", "mentioned bot", 620, 0.62, memory_ids, "normal")
        if not settings.shion_auto_reply_enabled:
            return Decision(False, "none", "auto reply disabled", 0, 0.0, memory_ids, "normal")
        level = settings.shion_auto_reply_level
        seconds = LEVEL_SECONDS.get(level, 1800)
        probability = LEVEL_PROBABILITY.get(level, 0.08)
        now = time.monotonic()
        if self._cooldowns.get(observation.group_id, 0) > now:
            return Decision(False, "none", "cooldown", 0, 0.0, memory_ids, "normal")
        interesting = observation.features.get("has_laugh") or observation.features.get("has_distress")
        if not interesting or random.random() > probability:
            return Decision(False, "none", "low priority", 0, 0.0, memory_ids, "normal")
        self._cooldowns[observation.group_id] = now + seconds
        return Decision(True, "ambient", "interesting low-frequency moment", 260, 0.68, memory_ids, "normal")


class ShionBrain:
    def __init__(
        self,
        *,
        store: SQLiteMemoryStore | None = None,
        mood_engine: MoodEngine | None = None,
        planner: Planner | None = None,
        generator: ReplyGenerator | None = None,
        critic: Critic | None = None,
    ) -> None:
        self.store = store or SQLiteMemoryStore()
        self.mood_engine = mood_engine or MoodEngine()
        self.persona_engine = PersonaEngine()
        self.retriever = Retriever(self.store)
        self.planner = planner or Planner()
        self.critic = critic or Critic()
        self.generator = generator or ReplyGenerator(critic=self.critic)
        self.self_state_store = SelfStateStore(self.store.path)
        self.thought_queue = ThoughtQueue(self.store.path)
        self.motivation_planner = MotivationPlanner(
            thought_queue=self.thought_queue,
            semantic_store=self.store,
            min_auto_reply_score=0.72,
            min_deep_score=0.55,
        )
        self._initialized = False
        self._last_reply_status: dict[str, ReplyStatus] = {}
        self._relationship_score: dict[str, float] = {}

    async def initialize(self) -> None:
        if not self._initialized:
            await self.store.initialize()
            await self.self_state_store.initialize()
            await self.thought_queue.initialize()
            self._initialized = True

    async def observe(self, observation: Observation) -> str | None:
        if not get_settings().shion_brain_enabled:
            return None
        await self.initialize()
        await self.store.save_observation(observation)
        mood = self.mood_engine.update(observation)
        self_state = await self.self_state_store.update_self_state(observation.group_id, observation)
        if self._is_confusion(observation):
            await self.thought_queue.raise_priority_for_repair(observation.group_id, observation.user_id)
        pending_thoughts = await self.thought_queue.list_pending_thoughts(observation.group_id, limit=5)
        memories = await self.retriever.retrieve(observation)
        cognitive_memories = await self._retrieve_cognitive_context(observation)
        all_memories = memories + cognitive_memories
        repair = self._repair_if_confused(observation)
        if repair:
            self._remember_status(observation, "success", "repaired previous failed reply", repair)
            await self._mark_repair_thoughts_done(pending_thoughts)
            await self.self_state_store.update_self_state(observation.group_id, observation, {"status": "success", "reason": "repaired previous failed reply"})
            return repair
        base_decision = self.planner.decide(observation, all_memories)
        cognitive_patch = await self.motivation_planner.decide_cognitive_patch(
            observation=observation,
            base_decision=base_decision,
            self_state=self_state,
            pending_thoughts=pending_thoughts,
            retrieved_memories=all_memories,
            cooldown_ok=base_decision.reason != "cooldown",
            ambient_enabled=get_settings().shion_auto_reply_enabled,
        )
        await self._maybe_create_agenda(observation, self_state, cognitive_patch, all_memories)
        decision = self._merge_cognitive_decision(base_decision, cognitive_patch, observation, all_memories)
        if not decision.should_reply:
            return None
        return await self._generate_checked_reply(observation, mood, all_memories, decision, entry="ambient", self_state_summary=render_self_state_for_prompt(self_state), pending_thoughts=pending_thoughts)

    async def respond_direct(self, observation: Observation) -> str | None:
        if not get_settings().shion_brain_enabled:
            return None
        await self.initialize()
        await self.store.save_observation(observation)
        mood = self.mood_engine.update(observation)
        self_state = await self.self_state_store.update_self_state(observation.group_id, observation)
        if self._is_confusion(observation):
            await self.thought_queue.raise_priority_for_repair(observation.group_id, observation.user_id)
        pending_thoughts = await self.thought_queue.list_pending_thoughts(observation.group_id, limit=5)
        memories = await self.retriever.retrieve(observation)
        cognitive_memories = await self._retrieve_cognitive_context(observation)
        all_memories = memories + cognitive_memories
        repair = self._repair_if_confused(observation)
        if repair:
            self._remember_status(observation, "success", "repaired previous failed reply", repair)
            await self._mark_repair_thoughts_done(pending_thoughts)
            await self.self_state_store.update_self_state(observation.group_id, observation, {"status": "success", "reason": "repaired previous failed reply"})
            return repair
        memory_ids = [memory.id for memory in all_memories[:8]]
        base_decision = Decision(
            True,
            "direct",
            "explicit mention or direct persona cue; force Gemini generation path",
            650,
            0.64,
            memory_ids,
            "strict" if observation.features.get("has_sensitive") else "normal",
        )
        cognitive_patch = await self.motivation_planner.decide_cognitive_patch(
            observation=observation,
            base_decision=base_decision,
            self_state=self_state,
            pending_thoughts=pending_thoughts,
            retrieved_memories=all_memories,
            cooldown_ok=True,
            ambient_enabled=True,
        )
        await self._maybe_create_agenda(observation, self_state, cognitive_patch, all_memories)
        decision = self._merge_cognitive_decision(base_decision, cognitive_patch, observation, all_memories, force_reply=True)
        return await self._generate_checked_reply(observation, mood, all_memories, decision, entry="direct", self_state_summary=render_self_state_for_prompt(self_state), pending_thoughts=pending_thoughts)

    async def generate_persona_intro(self, observation: Observation) -> str:
        await self.initialize()
        await self.store.save_observation(observation)
        group = observation.group_id
        mood = self.mood_engine.update(observation)
        self_state = await self.self_state_store.update_self_state(group, observation)
        pending_thoughts = await self.thought_queue.list_pending_thoughts(group, limit=5)
        memories = await self.retriever.retrieve(observation, limit=10)
        cognitive_memories = await self._retrieve_cognitive_context(observation)
        all_memories = memories + cognitive_memories
        decision = Decision(True, "intro", "user requested persona intro", 720, 0.48, [m.id for m in all_memories[:8]], "normal")
        return await self._generate_checked_reply(
            observation,
            mood,
            all_memories,
            decision,
            entry="persona_intro",
            self_state_summary=render_self_state_for_prompt(self_state),
            pending_thoughts=pending_thoughts,
        ) or FAILURE_REPLY

    async def _generate_checked_reply(
        self,
        observation: Observation,
        mood,
        memories: list[Memory],
        decision: Decision,
        *,
        entry: str,
        self_state_summary: str = "",
        pending_thoughts: list[Thought] | None = None,
    ) -> str | None:
        pending_thoughts = pending_thoughts or []
        reply = await self.generator.generate(
            observation,
            mood,
            memories,
            decision,
            entry=entry,
            self_state_summary=self_state_summary,
            pending_thoughts=pending_thoughts,
        )
        verdict = self.critic.check(reply, decision=decision)
        if verdict.ok:
            status = "failed" if reply == FAILURE_REPLY else "success"
            self._remember_status(observation, status, verdict.reason, verdict.text)
            self._adjust_relationship(observation, success=reply != FAILURE_REPLY)
            if status == "success":
                await self._mark_repair_thoughts_done(pending_thoughts)
            else:
                await self._create_repair_thought(observation, "LLM generation failed")
            await self.self_state_store.update_self_state(observation.group_id, observation, {"status": status, "reason": verdict.reason or status})
            return verdict.text
        replacement = verdict.replacement or FAILURE_REPLY
        status = "blocked" if replacement == SENSITIVE_BLOCK_REPLY else "low_quality"
        self._remember_status(observation, status, verdict.reason, replacement)
        await self._create_repair_thought(observation, verdict.reason or "reply rejected")
        await self.self_state_store.update_self_state(observation.group_id, observation, {"status": status, "reason": verdict.reason})
        self._adjust_relationship(observation, success=False)
        return replacement

    async def _retrieve_cognitive_context(self, observation: Observation) -> list[Memory]:
        memories: list[Memory] = []
        now = utc_now()
        try:
            semantic_edges = await self.store.search_semantic_edges(observation.group_id, limit=5)
            for edge in semantic_edges:
                memories.append(
                    Memory(
                        id=edge.id,
                        scope="group",
                        scope_id=observation.group_id,
                        type="semantic",
                        content=(
                            "长期语义记忆（弱参考，不要原样说出）："
                            f"{edge.subject} {edge.relation} {edge.object_value}，置信度 {edge.confidence:.2f}"
                        ),
                        tags=["semantic", *edge.tags],
                        importance=edge.confidence,
                        created_at=edge.created_at,
                        last_accessed_at=edge.updated_at,
                        access_count=0,
                    )
                )
        except Exception:
            logger.exception("Failed to retrieve semantic cognitive context for scope=%s", observation.group_id)
        try:
            beliefs = await self.store.retrieve_beliefs(scope_id=observation.group_id, limit=4)
            for belief in beliefs:
                memories.append(
                    Memory(
                        id=belief.id,
                        scope="group",
                        scope_id=observation.group_id,
                        type="semantic",
                        content=(
                            "信念状态（不确定假设，不要当事实）："
                            f"关于 {belief.subject}，{belief.hypothesis}，概率 {belief.probability:.2f}。{belief.uncertainty_note}"
                        ),
                        tags=["belief"],
                        importance=belief.probability,
                        created_at=belief.updated_at,
                        last_accessed_at=belief.updated_at,
                        access_count=0,
                    )
                )
        except Exception:
            logger.exception("Failed to retrieve belief cognitive context for scope=%s", observation.group_id)
        try:
            procedural = await self.store.retrieve_procedural_prompts(
                scope_id=observation.group_id,
                user_id=observation.user_id,
                limit=4,
            )
            for prompt in procedural:
                memories.append(
                    Memory(
                        id=prompt.id,
                        scope="group",
                        scope_id=observation.group_id,
                        type="semantic",
                        content=(
                            "程序/行为记忆（用于调整回复策略）："
                            f"场景 {prompt.context_signature}，倾向 {prompt.style_hint}，做法：{prompt.prompt_delta}，有效度 {prompt.effectiveness:.2f}"
                        ),
                        tags=["procedural", *prompt.tags],
                        importance=prompt.effectiveness,
                        created_at=prompt.created_at,
                        last_accessed_at=prompt.updated_at,
                        access_count=0,
                    )
                )
        except Exception:
            logger.exception("Failed to retrieve procedural cognitive context for scope=%s", observation.group_id)
        if not memories:
            return []
        memories.sort(key=lambda memory: memory.importance, reverse=True)
        return memories[:10]

    def _merge_cognitive_decision(
        self,
        base_decision: Decision,
        patch: CognitiveDecisionPatch,
        observation: Observation,
        memories: list[Memory],
        *,
        force_reply: bool = False,
    ) -> Decision:
        if patch.reply_intent == "stay_silent" and not base_decision.should_reply and not force_reply:
            return base_decision
        should_reply = force_reply or base_decision.should_reply or patch.reply_intent != "stay_silent"
        if not should_reply:
            return base_decision
        max_length = _intent_max_length(patch.reply_intent, base_decision.max_length)
        temperature = _intent_temperature(patch.reply_intent, base_decision.temperature)
        reason = f"{base_decision.reason}; cognitive_intent={patch.reply_intent}; meta={patch.meta_motivation_score:.2f}"
        return Decision(
            should_reply=True,
            reply_type=patch.reply_intent if patch.reply_intent != "stay_silent" else base_decision.reply_type,
            reason=reason,
            max_length=max_length,
            temperature=temperature,
            memory_ids=[memory.id for memory in memories[:8]],
            safety_level="strict" if observation.features.get("has_sensitive") else base_decision.safety_level,
            motivation_score=patch.motivation_score,
            meta_motivation_score=patch.meta_motivation_score,
            reply_intent=patch.reply_intent,
            internal_notes=patch.internal_notes,
            allowed_actions=patch.allowed_actions,
            incubation_required=patch.incubation_required,
            incubation_reason=patch.incubation_reason,
        )


    async def _maybe_create_agenda(
        self,
        observation: Observation,
        self_state,
        patch: CognitiveDecisionPatch,
        memories: list[Memory],
    ) -> None:
        if observation.is_command or observation.features.get("has_sensitive"):
            return
        try:
            scope_id = observation.group_id
            if getattr(self_state, "curiosity", 0.0) > 0.8 and not await self.store.has_active_agenda(scope_id, goal_type="curiosity_exploration"):
                await self.store.create_agenda_item(
                    AgendaItem(
                        id=new_id("agenda"),
                        scope_id=scope_id,
                        target_user_id=observation.user_id,
                        goal_type="curiosity_exploration",
                        description=(
                            "围绕近期对话中反复出现的话题，准备一个克制的启发式问题；"
                            "只在生命周期调度确认群聊安静时再主动输出。"
                        ),
                        priority=0.62,
                        metrics_trigger={"curiosity_gt": 0.8, "source_observation_id": observation.id},
                    )
                )
            if patch.meta_motivation_score >= 0.55 and patch.reply_intent in {"synthesize", "challenge"}:
                goal_type = "knowledge_synthesis" if patch.reply_intent == "synthesize" else "challenge"
                if not await self.store.has_active_agenda(scope_id, goal_type=goal_type):
                    await self.store.create_agenda_item(
                        AgendaItem(
                            id=new_id("agenda"),
                            scope_id=scope_id,
                            target_user_id=observation.user_id,
                            goal_type=goal_type,
                            description=(
                                "把近期复杂讨论整理成一个高价值、低打扰的后续洞察；"
                                "如果是 challenge，只提出温和质疑，不压迫对话。"
                            ),
                            priority=min(0.9, 0.58 + patch.meta_motivation_score * 0.35),
                            metrics_trigger={
                                "meta_motivation_gte": 0.55,
                                "reply_intent": patch.reply_intent,
                                "memory_count": len(memories),
                                "source_observation_id": observation.id,
                            },
                        )
                    )
        except Exception:
            logger.exception("Failed to derive agenda for scope=%s", observation.group_id)

    async def get_self_state_summary(self, scope_id: str) -> str:
        await self.initialize()
        return render_self_state_for_prompt(await self.self_state_store.get_self_state(scope_id))

    def _status_key(self, observation: Observation) -> str:
        return f"{observation.group_id}:{observation.user_id}"

    def _remember_status(self, observation: Observation, status: str, reason: str, bot_reply: str) -> None:
        self._last_reply_status[self._status_key(observation)] = ReplyStatus(
            status=status,
            reason=reason,
            user_message=observation.text,
            bot_reply=bot_reply,
            timestamp=time.monotonic(),
        )

    def _repair_if_confused(self, observation: Observation) -> str | None:
        status = self._last_reply_status.get(self._status_key(observation))
        if not status or status.status not in {"failed", "low_quality"}:
            return None
        if time.monotonic() - status.timestamp > 180:
            return None
        if not CONFUSION_RE.match(observation.text.strip()):
            return None
        if "中午" in status.user_message:
            return "刚才那句我没组织好。你问的是中午吧？如果按我的状态来说，中午更像是在整理记忆、翻聊天记录，然后发了一会儿呆。突然查岗吗？"
        if "the maintainer" in status.user_message.lower():
            return "刚才没答好。the maintainer 给我的感觉是脑子转得很快、但经常同时开太多坑的人；有时候像在调项目，有时候像在调自己。挺有趣的。"
        return f"刚才那句我没组织好。你刚刚问的是“{status.user_message[:40]}”，我会按这个重新接，不继续糊弄过去。"

    def _is_confusion(self, observation: Observation) -> bool:
        return bool(CONFUSION_RE.match(observation.text.strip()))

    async def _create_repair_thought(self, observation: Observation, reason: str) -> None:
        await self.thought_queue.create_thought(
            scope_id=observation.group_id,
            user_id=observation.user_id,
            type="repair",
            content=f"{reason}；下一次要更直接地回应：{observation.text[:80]}",
            priority=0.78,
            source_observation_id=observation.id,
        )

    async def _mark_repair_thoughts_done(self, thoughts: list[Thought]) -> None:
        for thought in thoughts:
            if thought.type == "repair":
                await self.thought_queue.mark_thought_done(thought.id)

    def _adjust_relationship(self, observation: Observation, *, success: bool) -> None:
        key = self._status_key(observation)
        score = self._relationship_score.get(key, 0.5)
        if observation.mentions_bot:
            score += 0.01
        score += 0.01 if success else -0.02
        self._relationship_score[key] = min(1.0, max(0.0, score))


def _intent_max_length(intent: str, base: int) -> int:
    base = base or 260
    if intent in {"synthesize", "challenge", "inspire"}:
        return max(base, 520)
    if intent == "repair":
        return max(base, 360)
    if intent == "ask_clarification":
        return min(max(base, 220), 360)
    return base


def _intent_temperature(intent: str, base: float) -> float:
    if intent in {"synthesize", "challenge", "repair"}:
        return min(base or 0.55, 0.5)
    if intent == "inspire":
        return max(base or 0.6, 0.62)
    return base or 0.6


brain = ShionBrain()
