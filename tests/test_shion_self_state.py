from __future__ import annotations

import pytest

from src.chatbot.shion_brain.models import Observation, utc_now
from src.chatbot.shion_brain.self_state import SelfStateStore, render_self_state_for_prompt


@pytest.fixture
def anyio_backend():
    return "asyncio"


def observation(text: str, *, features: dict | None = None) -> Observation:
    return Observation(
        id=f"obs-{abs(hash(text))}",
        group_id="group-1",
        user_id="user-1",
        message_id="msg-1",
        text=text,
        timestamp=utc_now(),
        message_type="group",
        is_command=False,
        mentions_bot=False,
        features=features or {},
    )


@pytest.mark.anyio
async def test_self_state_initializes(tmp_path):
    store = SelfStateStore(tmp_path / "shion.db")
    await store.initialize()

    state = await store.get_self_state("group-1")

    assert state.scope_id == "group-1"
    assert 0.0 <= state.energy <= 1.0
    assert render_self_state_for_prompt(state)


@pytest.mark.anyio
async def test_confusion_raises_stress_and_focus(tmp_path):
    store = SelfStateStore(tmp_path / "shion.db")
    before = await store.get_self_state("group-1")

    after = await store.update_self_state("group-1", observation("没懂"))

    assert after.stress > before.stress
    assert after.focus > before.focus


@pytest.mark.anyio
async def test_positive_interaction_raises_social_warmth(tmp_path):
    store = SelfStateStore(tmp_path / "shion.db")
    before = await store.get_self_state("group-1")

    after = await store.update_self_state("group-1", observation("谢谢，挺好用的"))

    assert after.social_warmth > before.social_warmth
    assert after.energy > before.energy


@pytest.mark.anyio
async def test_failure_records_recent_mistake(tmp_path):
    store = SelfStateStore(tmp_path / "shion.db")

    state = await store.update_self_state(
        "group-1",
        observation("shion 解释一下这个报错"),
        {"status": "failed", "reason": "Gemini generation failed"},
    )

    assert state.stress > 0.18
    assert state.recent_mistakes
    assert "Gemini" in state.recent_mistakes[-1]
