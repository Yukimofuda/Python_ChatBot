from __future__ import annotations

import sqlite3

import pytest

from src.chatbot.shion_brain.memory_store import SQLiteMemoryStore
from src.chatbot.shion_brain.models import AgendaItem, BeliefHypothesis, DistilledMemory, ProceduralPrompt, SemanticEdge, new_id


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_semantic_edge_upsert_and_conflict_resolution(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "shion.db")
    await store.initialize()
    old = SemanticEdge(
        id=new_id("sem"),
        scope="group",
        scope_id="g1",
        subject="style:group",
        relation="prefers_style",
        object_value="多用 emoji",
        confidence=0.4,
        conflict_group="style_emoji_usage",
    )
    new = SemanticEdge(
        id=new_id("sem"),
        scope="group",
        scope_id="g1",
        subject="style:group",
        relation="prefers_style",
        object_value="少用 emoji，直接一点",
        confidence=0.8,
        conflict_group="style_emoji_usage",
    )

    assert await store.upsert_semantic_edge(old) == old.id
    assert await store.upsert_semantic_edge(new) == new.id
    edges = await store.search_semantic_edges("g1", relation="prefers_style")

    assert [edge.id for edge in edges] == [new.id]
    assert edges[0].object_value == "少用 emoji，直接一点"


@pytest.mark.anyio
async def test_procedural_prompt_success_score_updates(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "shion.db")
    await store.initialize()

    await store.record_procedural_outcome(
        scope_id="g1",
        user_id="u1",
        context_signature="repair_after_confusion",
        style_hint="more_direct",
        prompt_delta="先直接重说，不玩梗。",
        outcome="success",
    )
    await store.record_procedural_outcome(
        scope_id="g1",
        user_id="u1",
        context_signature="repair_after_confusion",
        style_hint="more_direct",
        prompt_delta="先直接重说，不玩梗。",
        outcome="success",
    )
    prompts = await store.retrieve_procedural_prompts(scope_id="g1", user_id="u1")

    assert len(prompts) == 1
    assert prompts[0].success_score == 2.0
    assert prompts[0].effectiveness > 0.99


@pytest.mark.anyio
async def test_belief_state_probability_clamped(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "shion.db")
    await store.initialize()
    belief = BeliefHypothesis(
        id=new_id("belief"),
        scope_id="g1",
        subject="user:u1",
        hypothesis="用户可能更喜欢短句。",
        probability=9.0,
    )

    await store.upsert_belief(belief)
    beliefs = await store.retrieve_beliefs(scope_id="g1", subject="user:u1")

    assert beliefs[0].probability == 1.0


@pytest.mark.anyio
async def test_save_distillation_result_writes_all_memory_types(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "shion.db")
    await store.initialize()
    result = DistilledMemory(
        id=new_id("distill"),
        scope_id="g1",
        reflection_type="consolidation",
        summary="用户更喜欢直接解释。",
        semantic_edges=[
            SemanticEdge(
                id=new_id("sem"),
                scope="group",
                scope_id="g1",
                subject="style:group",
                relation="prefers_style",
                object_value="直接一点",
                confidence=0.7,
            )
        ],
        belief_updates=[
            BeliefHypothesis(
                id=new_id("belief"),
                scope_id="g1",
                subject="group:g1",
                hypothesis="群聊可能更喜欢短回复。",
                probability=0.6,
            )
        ],
        procedural_updates=[
            ProceduralPrompt(
                id=new_id("proc"),
                scope_id="g1",
                user_id=None,
                context_signature="general_reply",
                style_hint="concise",
                prompt_delta="回复短一点。",
                last_outcome="success",
            )
        ],
    )

    await store.save_distillation_result(result)

    assert await store.search_semantic_edges("g1")
    assert await store.retrieve_beliefs(scope_id="g1")
    assert await store.retrieve_procedural_prompts(scope_id="g1", user_id=None)


@pytest.mark.anyio
async def test_semantic_conflict_record_written(tmp_path):
    db = tmp_path / "shion.db"
    store = SQLiteMemoryStore(db)
    await store.initialize()
    old = SemanticEdge(
        id=new_id("sem"),
        scope="group",
        scope_id="g1",
        subject="project:x",
        relation="status",
        object_value="blocked",
        confidence=0.3,
    )
    new = SemanticEdge(
        id=new_id("sem"),
        scope="group",
        scope_id="g1",
        subject="project:x",
        relation="status",
        object_value="fixed",
        confidence=0.9,
    )

    await store.upsert_semantic_edge(old)
    await store.upsert_semantic_edge(new)

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        old_row = conn.execute("SELECT is_active FROM shion_semantic_graph WHERE id = ?", (old.id,)).fetchone()
        conflict = conn.execute("SELECT * FROM shion_memory_conflicts WHERE winning_memory_id = ?", (new.id,)).fetchone()

    assert old_row["is_active"] == 0
    assert conflict is not None
    assert old.id in conflict["losing_memory_ids"]


@pytest.mark.anyio
async def test_belief_conflict_new_high_probability_wins(tmp_path):
    db = tmp_path / "shion.db"
    store = SQLiteMemoryStore(db)
    await store.initialize()
    old = BeliefHypothesis(
        id=new_id("belief"),
        scope_id="g1",
        subject="user:u1",
        hypothesis="用户可能喜欢很长的解释。",
        probability=0.35,
    )
    new = BeliefHypothesis(
        id=new_id("belief"),
        scope_id="g1",
        subject="user:u1",
        hypothesis="用户可能喜欢短句和直接结论。",
        probability=0.92,
    )

    await store.upsert_belief(old)
    await store.upsert_belief(new)

    beliefs = await store.retrieve_beliefs(scope_id="g1", subject="user:u1")
    assert [belief.id for belief in beliefs] == [new.id]
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        conflict = conn.execute("SELECT * FROM shion_memory_conflicts WHERE winning_memory_id = ?", (new.id,)).fetchone()
    assert conflict is not None
    assert old.id in conflict["losing_memory_ids"]


@pytest.mark.anyio
async def test_agenda_crud(tmp_path):
    store = SQLiteMemoryStore(tmp_path / "shion.db")
    await store.initialize()
    item = AgendaItem(
        id=new_id("agenda"),
        scope_id="123456",
        target_user_id="u1",
        goal_type="curiosity_exploration",
        description="准备一个低频启发式问题。",
        priority=0.8,
        metrics_trigger={"curiosity_gt": 0.8},
    )

    assert await store.create_agenda_item(item) == item.id
    assert await store.has_active_agenda("123456", goal_type="curiosity_exploration") is True
    active = await store.list_active_agenda_items("123456")
    assert active[0].id == item.id
    await store.deprioritize_agenda_item(item.id, amount=0.2)
    active = await store.list_active_agenda_items("123456")
    assert 0.5 < active[0].priority < 0.8
    await store.complete_agenda_item(item.id)
    assert await store.has_active_agenda("123456") is False
