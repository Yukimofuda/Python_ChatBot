from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.chatbot.shion_brain.models import CognitiveDecisionPatch, Observation, utc_now
from src.chatbot.shion_brain.memory_store import SQLiteMemoryStore
from src.chatbot.shion_brain.planner import MotivationPlanner, ShionBrain
from src.chatbot.shion_brain.thought_queue import ThoughtQueue


@pytest.fixture
def anyio_backend():
    return "asyncio"


def observation(text: str, *, mentions: bool = False, features: dict | None = None) -> Observation:
    return Observation(
        id=f"obs-{abs(hash(text))}",
        group_id="g1",
        user_id="u1",
        message_id="m1",
        text=text,
        timestamp=utc_now(),
        message_type="group",
        is_command=False,
        mentions_bot=mentions,
        features=features or {},
    )


@pytest.mark.anyio
async def test_planner_selects_repair_for_confusion():
    planner = MotivationPlanner(min_auto_reply_score=0.1)

    patch = await planner.decide_cognitive_patch(observation=observation("什么鬼？"), cooldown_ok=True)

    assert patch.reply_intent == "repair"
    assert "reply" in patch.allowed_actions


@pytest.mark.anyio
async def test_planner_selects_synthesize_for_complex_discussion():
    planner = MotivationPlanner(min_auto_reply_score=0.1, min_deep_score=0.2)

    patch = await planner.decide_cognitive_patch(
        observation=observation("总结一下大家刚才这段讨论"),
        retrieved_memories=[object()] * 8,
        cooldown_ok=True,
    )

    assert patch.reply_intent == "synthesize"


@pytest.mark.anyio
async def test_planner_suppresses_tease_under_distress():
    planner = MotivationPlanner(min_auto_reply_score=0.1)

    patch = await planner.decide_cognitive_patch(observation=observation("救命，代码又崩了"), cooldown_ok=True)

    assert patch.reply_intent in {"comfort", "inspire", "answer"}
    assert patch.reply_intent != "tease"


@pytest.mark.anyio
async def test_incubation_thought_created_for_complex_non_mention_discussion(tmp_path):
    queue = ThoughtQueue(tmp_path / "shion.db")
    await queue.initialize()
    planner = MotivationPlanner(thought_queue=queue, min_auto_reply_score=0.1, min_deep_score=0.2)

    patch = await planner.decide_cognitive_patch(
        observation=observation("整理一下这段讨论，感觉这里有逻辑矛盾"),
        retrieved_memories=[object()] * 8,
        cooldown_ok=True,
    )
    thoughts = await queue.list_pending_thoughts("g1")

    assert patch.reply_intent in {"synthesize", "challenge"}
    assert patch.incubation_required is True
    assert thoughts


@pytest.mark.anyio
async def test_brain_derives_curiosity_agenda(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "shion.db")
    brain = ShionBrain(store=store)
    await brain.initialize()
    obs = observation("最近这个项目还有什么可以继续挖的？")
    state = SimpleNamespace(curiosity=0.91)
    patch = CognitiveDecisionPatch(reply_intent="answer", meta_motivation_score=0.2)

    await brain._maybe_create_agenda(obs, state, patch, [])

    items = await store.list_active_agenda_items("g1")
    assert items
    assert items[0].goal_type == "curiosity_exploration"
