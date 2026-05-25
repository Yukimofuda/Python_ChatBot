from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from nonebot import get_bot, logger, require

from src.chatbot.shion_brain.critic import FAILURE_REPLY, SENSITIVE_BLOCK_REPLY
from src.chatbot.shion_brain.generator import ReplyGenerator
from src.chatbot.shion_brain.memory_store import SQLiteMemoryStore
from src.chatbot.shion_brain.models import AgendaItem, Decision, Memory, Observation, utc_now
from src.chatbot.shion_brain.mood_engine import MoodEngine
from src.chatbot.shion_brain.reflection import AdaptiveReflectionEngine
from src.chatbot.shion_brain.self_state import SelfStateStore, render_self_state_for_prompt
from src.chatbot.shion_brain.thought_queue import Thought, ThoughtQueue

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler  # noqa: E402


@dataclass(frozen=True)
class LifecycleRuntime:
    store: SQLiteMemoryStore
    thought_queue: ThoughtQueue
    generator: ReplyGenerator
    mood_engine: MoodEngine
    self_state_store: SelfStateStore


_runtime = LifecycleRuntime(
    store=SQLiteMemoryStore(),
    thought_queue=ThoughtQueue(),
    generator=ReplyGenerator(),
    mood_engine=MoodEngine(),
    self_state_store=SelfStateStore(),
)
_metabolism_lock = asyncio.Lock()
_incubation_lock = asyncio.Lock()
_agenda_lock = asyncio.Lock()


async def _ensure_runtime() -> None:
    await _runtime.store.initialize()
    await _runtime.thought_queue.initialize()
    await _runtime.self_state_store.initialize()


@scheduler.scheduled_job(
    "interval",
    minutes=60,
    id="shion_brain_metabolism",
    coalesce=True,
    max_instances=1,
)
async def shion_brain_metabolism() -> None:
    if _metabolism_lock.locked():
        logger.warning("Shion lifecycle metabolism skipped: previous run still active")
        return
    async with _metabolism_lock:
        try:
            await _ensure_runtime()
            scopes = await _runtime.store.get_active_scopes(since_hours=3)
            if not scopes:
                logger.info("Shion lifecycle metabolism: no active scopes in recent window")
                return
            logger.info("Shion lifecycle metabolism started for %s active scopes", len(scopes))
            reflection = AdaptiveReflectionEngine(
                memory_store=_runtime.store,
                thought_queue=_runtime.thought_queue,
            )
            for scope_id in scopes:
                try:
                    result = await reflection.run_cycle(scope_id)
                    pruned = await _runtime.store.deactivate_stale_semantic_edges(scope_id=scope_id)
                    logger.info(
                        "Shion lifecycle metabolism finished scope=%s reflected=%s pruned=%s",
                        scope_id,
                        bool(result),
                        pruned,
                    )
                except Exception:
                    logger.exception("Shion lifecycle metabolism failed for scope=%s", scope_id)
        except Exception:
            logger.exception("Shion lifecycle metabolism crashed before scope loop")


@scheduler.scheduled_job(
    "interval",
    minutes=15,
    id="shion_incubation_wakeup",
    coalesce=True,
    max_instances=1,
)
async def check_incubating_thoughts() -> None:
    if _incubation_lock.locked():
        logger.warning("Shion incubation wake-up skipped: previous run still active")
        return
    async with _incubation_lock:
        try:
            await _ensure_runtime()
            thoughts = await _runtime.thought_queue.list_incubating_thoughts(min_age_minutes=30, limit=5)
            if not thoughts:
                return
            logger.info("Shion incubation wake-up found %s ready thoughts", len(thoughts))
            for thought in thoughts:
                await _wake_one_thought(thought)
        except Exception:
            logger.exception("Shion incubation wake-up crashed")


@scheduler.scheduled_job(
    "interval",
    minutes=30,
    id="shion_agenda_focus",
    coalesce=True,
    max_instances=1,
)
async def execute_agenda_focus() -> None:
    if _agenda_lock.locked():
        logger.warning("Shion agenda focus skipped: previous run still active")
        return
    async with _agenda_lock:
        try:
            await _ensure_runtime()
            scopes = await _runtime.store.get_active_scopes(since_hours=6)
            if not scopes:
                return
            for scope_id in scopes:
                group_id = _parse_group_id(scope_id)
                if group_id is None:
                    logger.warning("Skip agenda focus for non-group scope=%s", scope_id)
                    continue
                try:
                    agenda_items = await _runtime.store.list_active_agenda_items(scope_id, limit=1)
                    if not agenda_items:
                        continue
                    agenda = agenda_items[0]
                    state = await _runtime.self_state_store.get_self_state(scope_id)
                    if not await _agenda_gate(scope_id, agenda, state):
                        continue
                    await _execute_one_agenda(group_id, agenda, state)
                except Exception:
                    logger.exception("Agenda focus failed for scope=%s", scope_id)
        except Exception:
            logger.exception("Shion agenda focus crashed before scope loop")


async def _wake_one_thought(thought: Thought) -> None:
    await _runtime.thought_queue.mark_thought_locked(thought.id)
    try:
        group_id = _parse_group_id(thought.scope_id)
        if group_id is None:
            logger.warning("Skip incubating thought without numeric group scope: thought=%s scope=%s", thought.id, thought.scope_id)
            await _runtime.thought_queue.dismiss_thought(thought.id)
            return
        memories = await _build_scope_memories(thought.scope_id)
        observation = Observation(
            id=f"incubation-{thought.id}",
            group_id=thought.scope_id,
            user_id=thought.user_id or "system",
            message_id=f"incubation-{thought.id}",
            text=(
                "后台孵化思考已完成。请基于这条内部 thought 和相关长期记忆，"
                "主动给群聊发一段高价值、简短、不像公告的洞察。"
                f"内部 thought：{thought.content}"
            ),
            timestamp=utc_now(),
            message_type="group",
            is_command=False,
            mentions_bot=False,
            features={"incubation_wakeup": True},
        )
        intent = _infer_intent(thought)
        decision = _proactive_decision(intent, memories, reason="incubating thought wake-up; proactive high-value insight")
        reply = await _runtime.generator.generate(
            observation,
            _runtime.mood_engine.get(thought.scope_id),
            memories,
            decision,
            entry="incubation_wakeup",
            self_state_summary="Shion 刚完成一段后台整理；这次只输出结论，不解释后台机制。",
            pending_thoughts=[thought],
        )
        if reply in {FAILURE_REPLY, SENSITIVE_BLOCK_REPLY}:
            logger.warning("Incubating thought generation did not produce sendable text: thought=%s", thought.id)
            await _runtime.thought_queue.mark_thought_incubating(thought.id)
            return
        await _send_group_message(group_id, reply)
        await _runtime.thought_queue.mark_thought_done(thought.id)
        logger.info("Incubating thought sent and completed: thought=%s group=%s", thought.id, group_id)
    except Exception:
        logger.exception("Failed to wake incubating thought: thought=%s scope=%s", thought.id, thought.scope_id)
        try:
            await _runtime.thought_queue.mark_thought_incubating(thought.id)
        except Exception:
            logger.exception("Failed to restore incubating thought status after wake failure: thought=%s", thought.id)


async def _execute_one_agenda(group_id: int, agenda: AgendaItem, state) -> None:
    try:
        memories = await _build_scope_memories(agenda.scope_id)
        intent = _agenda_intent(agenda)
        observation = Observation(
            id=f"agenda-{agenda.id}",
            group_id=agenda.scope_id,
            user_id=agenda.target_user_id or "system",
            message_id=f"agenda-{agenda.id}",
            text=(
                "这是一条由内部议程触发的低频主动思考。"
                "请结合 agenda 目标和近期上下文，生成一段自然、克制、有价值的群聊发言。"
                f"Agenda 类型：{agenda.goal_type}。目标：{agenda.description}"
            ),
            timestamp=utc_now(),
            message_type="group",
            is_command=False,
            mentions_bot=False,
            features={"agenda_focus": True, "agenda_goal_type": agenda.goal_type},
        )
        decision = _proactive_decision(intent, memories, reason=f"agenda focus: {agenda.goal_type}")
        reply = await _runtime.generator.generate(
            observation,
            _runtime.mood_engine.get(agenda.scope_id),
            memories,
            decision,
            entry="agenda_focus",
            self_state_summary=render_self_state_for_prompt(state),
            pending_thoughts=[],
        )
        if reply in {FAILURE_REPLY, SENSITIVE_BLOCK_REPLY}:
            logger.warning("Agenda generation returned non-sendable reply: agenda=%s", agenda.id)
            await _runtime.store.deprioritize_agenda_item(agenda.id, amount=0.18)
            return
        await _send_group_message(group_id, reply)
        await _runtime.store.complete_agenda_item(agenda.id)
        logger.info("Agenda item completed and sent: agenda=%s group=%s", agenda.id, group_id)
    except Exception:
        logger.exception("Failed to execute agenda item: agenda=%s scope=%s", agenda.id, agenda.scope_id)
        try:
            await _runtime.store.deprioritize_agenda_item(agenda.id, amount=0.12)
        except Exception:
            logger.exception("Failed to deprioritize agenda after execution failure: agenda=%s", agenda.id)


async def _agenda_gate(scope_id: str, agenda: AgendaItem, state) -> bool:
    if agenda.priority < 0.45:
        return False
    quiet = await _scope_is_quiet(scope_id)
    night = _is_late_night()
    stable_energy = 0.24 <= float(getattr(state, "energy", 0.6)) <= 0.78
    curious = float(getattr(state, "curiosity", 0.5)) >= 0.62
    if agenda.goal_type == "curiosity_exploration":
        return stable_energy and curious and (quiet or night)
    return stable_energy and (quiet or night or agenda.priority >= 0.78)


async def _scope_is_quiet(scope_id: str) -> bool:
    try:
        recent = await _runtime.store.recent(scope_id, limit=3)
        if not recent:
            return True
        newest = max(_parse_iso(memory.created_at) for memory in recent)
        return (datetime.now(timezone.utc) - newest).total_seconds() >= 15 * 60
    except Exception:
        logger.exception("Failed to check quiet scope for agenda focus: scope=%s", scope_id)
        return False


async def _build_scope_memories(scope_id: str) -> list[Memory]:
    memories: list[Memory] = []
    try:
        semantic_edges = await _runtime.store.search_semantic_edges(scope_id, limit=8)
        for edge in semantic_edges:
            memories.append(
                Memory(
                    id=edge.id,
                    scope="group",
                    scope_id=scope_id,
                    type="semantic",
                    content=f"长期语义记忆（弱参考）：{edge.subject} {edge.relation} {edge.object_value}，置信度 {edge.confidence:.2f}",
                    tags=["semantic", *edge.tags],
                    importance=edge.confidence,
                    created_at=edge.created_at,
                    last_accessed_at=edge.updated_at,
                    access_count=0,
                )
            )
    except Exception:
        logger.exception("Failed to load semantic context for scope=%s", scope_id)
    try:
        memories.extend(await _runtime.store.recent(scope_id, limit=8))
    except Exception:
        logger.exception("Failed to load recent context for scope=%s", scope_id)
    memories.sort(key=lambda memory: memory.importance, reverse=True)
    return memories[:12]


def _proactive_decision(intent: str, memories: list[Memory], *, reason: str) -> Decision:
    return Decision(
        should_reply=True,
        reply_type=intent,
        reason=reason,
        max_length=520 if intent in {"synthesize", "inspire", "challenge"} else 360,
        temperature=0.5 if intent in {"synthesize", "challenge"} else 0.62,
        memory_ids=[memory.id for memory in memories[:8]],
        safety_level="normal",
        motivation_score=0.86,
        meta_motivation_score=0.9,
        reply_intent=intent,
        internal_notes=["lifecycle_proactive"],
        allowed_actions=["reply", "proactive_send"],
        incubation_required=False,
    )


def _agenda_intent(agenda: AgendaItem) -> str:
    if agenda.goal_type == "challenge":
        return "challenge"
    if agenda.goal_type == "knowledge_synthesis":
        return "synthesize"
    return "inspire"


async def _send_group_message(group_id: int, message: str) -> None:
    try:
        bot = get_bot()
        await bot.send_group_msg(group_id=group_id, message=message)
    except Exception:
        logger.exception("Failed to proactively send Shion lifecycle message to group=%s", group_id)
        raise


def _parse_group_id(scope_id: str) -> int | None:
    match = re.fullmatch(r"(?:group:)?(\d+)", str(scope_id))
    if not match:
        return None
    return int(match.group(1))


def _infer_intent(thought: Thought) -> str:
    text = thought.content.lower()
    if "synthesize" in text or "总结" in thought.content or "讨论" in thought.content:
        return "synthesize"
    if "challenge" in text or "逻辑" in thought.content or "矛盾" in thought.content:
        return "challenge"
    if "inspire" in text or "启发" in thought.content:
        return "inspire"
    return "synthesize"


def _is_late_night() -> bool:
    hour = datetime.now().hour
    return hour >= 23 or hour < 6


def _parse_iso(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        logger.warning("Failed to parse timestamp for lifecycle quiet check: %s", value)
        return datetime.now(timezone.utc)
