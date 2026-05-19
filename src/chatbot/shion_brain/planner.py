from __future__ import annotations

from dataclasses import dataclass
import random
import re
import time

from src.chatbot.settings import get_settings
from src.chatbot.shion_brain.critic import FAILURE_REPLY, SENSITIVE_BLOCK_REPLY, Critic
from src.chatbot.shion_brain.generator import ReplyGenerator
from src.chatbot.shion_brain.memory_store import SQLiteMemoryStore
from src.chatbot.shion_brain.models import Decision, Memory, Observation
from src.chatbot.shion_brain.mood_engine import MoodEngine
from src.chatbot.shion_brain.persona_engine import PersonaEngine
from src.chatbot.shion_brain.retrieval import Retriever


LEVEL_SECONDS = {"low": 1800, "medium": 600, "high": 180}
LEVEL_PROBABILITY = {"low": 0.08, "medium": 0.16, "high": 0.25}
CONFUSION_RE = re.compile(r"^(\?|？|什么鬼|没懂|你在说什么|啊\?|哈\?|啥)$")


@dataclass
class ReplyStatus:
    status: str
    reason: str
    user_message: str
    bot_reply: str
    timestamp: float


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
        self._initialized = False
        self._last_reply_status: dict[str, ReplyStatus] = {}
        self._relationship_score: dict[str, float] = {}

    async def initialize(self) -> None:
        if not self._initialized:
            await self.store.initialize()
            self._initialized = True

    async def observe(self, observation: Observation) -> str | None:
        if not get_settings().shion_brain_enabled:
            return None
        await self.initialize()
        await self.store.save_observation(observation)
        mood = self.mood_engine.update(observation)
        memories = await self.retriever.retrieve(observation)
        repair = self._repair_if_confused(observation)
        if repair:
            self._remember_status(observation, "success", "repaired previous failed reply", repair)
            return repair
        decision = self.planner.decide(observation, memories)
        if not decision.should_reply:
            return None
        return await self._generate_checked_reply(observation, mood, memories, decision, entry="ambient")

    async def respond_direct(self, observation: Observation) -> str | None:
        if not get_settings().shion_brain_enabled:
            return None
        await self.initialize()
        await self.store.save_observation(observation)
        mood = self.mood_engine.update(observation)
        memories = await self.retriever.retrieve(observation)
        repair = self._repair_if_confused(observation)
        if repair:
            self._remember_status(observation, "success", "repaired previous failed reply", repair)
            return repair
        memory_ids = [memory.id for memory in memories[:6]]
        decision = Decision(
            True,
            "direct",
            "explicit mention or direct persona cue; force Gemini generation path",
            650,
            0.64,
            memory_ids,
            "strict" if observation.features.get("has_sensitive") else "normal",
        )
        return await self._generate_checked_reply(observation, mood, memories, decision, entry="direct")

    async def generate_persona_intro(self, observation: Observation) -> str:
        await self.initialize()
        await self.store.save_observation(observation)
        group = observation.group_id
        mood = self.mood_engine.update(observation)
        memories = await self.retriever.retrieve(observation, limit=10)
        decision = Decision(True, "intro", "user requested persona intro", 720, 0.48, [m.id for m in memories[:6]], "normal")
        return await self._generate_checked_reply(observation, mood, memories, decision, entry="persona_intro") or FAILURE_REPLY

    async def _generate_checked_reply(
        self,
        observation: Observation,
        mood,
        memories: list[Memory],
        decision: Decision,
        *,
        entry: str,
    ) -> str | None:
        reply = await self.generator.generate(observation, mood, memories, decision, entry=entry)
        verdict = self.critic.check(reply, decision=decision)
        if verdict.ok:
            self._remember_status(observation, "failed" if reply == FAILURE_REPLY else "success", verdict.reason, verdict.text)
            self._adjust_relationship(observation, success=reply != FAILURE_REPLY)
            return verdict.text
        replacement = verdict.replacement or FAILURE_REPLY
        self._remember_status(observation, "blocked" if replacement == SENSITIVE_BLOCK_REPLY else "low_quality", verdict.reason, replacement)
        self._adjust_relationship(observation, success=False)
        return replacement

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
        if "yuki" in status.user_message.lower():
            return "刚才没答好。Yuki 给我的感觉是脑子转得很快、但经常同时开太多坑的人；有时候像在调项目，有时候像在调自己。挺有趣的。"
        return f"刚才那句我没组织好。你刚刚问的是“{status.user_message[:40]}”，我会按这个重新接，不继续糊弄过去。"

    def _adjust_relationship(self, observation: Observation, *, success: bool) -> None:
        key = self._status_key(observation)
        score = self._relationship_score.get(key, 0.5)
        if observation.mentions_bot:
            score += 0.01
        score += 0.01 if success else -0.02
        self._relationship_score[key] = min(1.0, max(0.0, score))


brain = ShionBrain()
