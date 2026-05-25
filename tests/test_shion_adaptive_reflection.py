from __future__ import annotations

import pytest

from src.chatbot.shion_brain.memory_store import SQLiteMemoryStore
from src.chatbot.shion_brain.models import Observation, utc_now
from src.chatbot.shion_brain.reflection import AdaptiveReflectionEngine, ReflectionOutput, redact_sensitive


@pytest.fixture
def anyio_backend():
    return "asyncio"


def obs(text: str, id_: str) -> Observation:
    return Observation(
        id=id_,
        group_id="g1",
        user_id="u1",
        message_id=id_,
        text=text,
        timestamp=utc_now(),
        message_type="group",
        is_command=False,
        mentions_bot=False,
        features={},
    )


@pytest.mark.anyio
async def test_reflection_rule_fallback_filters_sensitive_tokens(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "shion.db")
    await store.initialize()
    await store.save_observation(obs("别用 emoji，token=secret_value_should_be_redacted", "o1"))
    engine = AdaptiveReflectionEngine(memory_store=store)

    result = await engine.run_cycle("g1")

    assert result is not None
    assert result.semantic_edges
    combined = " ".join(edge.object_value for edge in result.semantic_edges)
    assert "secret_value" not in combined


@pytest.mark.anyio
async def test_reflection_saves_distilled_memory(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "shion.db")
    await store.initialize()
    await store.save_observation(obs("没懂，啥意思？", "o1"))
    engine = AdaptiveReflectionEngine(memory_store=store)

    result = await engine.run_cycle("g1")
    prompts = await store.retrieve_procedural_prompts(scope_id="g1", user_id=None)

    assert result is not None
    assert result.surprise_score >= 0.5
    assert any(prompt.context_signature == "repair_after_confusion" for prompt in prompts)


def test_redact_sensitive():
    assert ("sk" + "-") not in redact_sensitive("token=abc token=abcdefghijklmnopqrstuvwxyz")


def test_convert_output_skips_bad_sensitive_candidate(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "shion.db")
    engine = AdaptiveReflectionEngine(memory_store=store)
    output = ReflectionOutput(
        prospective_prediction="",
        retrospective_note="",
        surprise_score=0.2,
        semantic_candidates=[
            {
                "subject": "user:u1",
                "relation": "leaked",
                "object_value": "token=abc123456789",
                "confidence": 0.9,
            }
        ],
        belief_candidates=[],
        procedural_candidates=[],
        stale_memory_ids=[],
        summary="skip bad",
    )

    result = engine._convert_output("g1", output)

    assert result.semantic_edges == []
