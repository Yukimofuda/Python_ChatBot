from __future__ import annotations

import pytest

from src.chatbot.shion_brain.thought_queue import ThoughtQueue, summarize_thoughts


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_create_pending_thought(tmp_path):
    queue = ThoughtQueue(tmp_path / "shion.db")
    await queue.initialize()

    thought = await queue.create_thought(scope_id="group-1", user_id="user-1", type="repair", content="上一次没答好", priority=0.4)
    pending = await queue.list_pending_thoughts("group-1")

    assert thought is not None
    assert pending[0].id == thought.id
    assert "更直接" in summarize_thoughts(pending)


@pytest.mark.anyio
async def test_sensitive_thought_is_not_saved(tmp_path):
    queue = ThoughtQueue(tmp_path / "shion.db")
    await queue.initialize()

    thought = await queue.create_thought(scope_id="group-1", type="repair", content="token=secret_value_should_be_redacted")
    pending = await queue.list_pending_thoughts("group-1")

    assert thought is None
    assert pending == []


@pytest.mark.anyio
async def test_raise_priority_for_repair(tmp_path):
    queue = ThoughtQueue(tmp_path / "shion.db")
    await queue.initialize()
    thought = await queue.create_thought(scope_id="group-1", user_id="user-1", type="repair", content="需要重答", priority=0.2)
    assert thought is not None

    await queue.raise_priority_for_repair("group-1", "user-1")
    pending = await queue.list_pending_thoughts("group-1")

    assert pending[0].priority > thought.priority


@pytest.mark.anyio
async def test_done_thought_not_pending(tmp_path):
    queue = ThoughtQueue(tmp_path / "shion.db")
    await queue.initialize()
    thought = await queue.create_thought(scope_id="group-1", type="repair", content="修正一下", priority=0.5)
    assert thought is not None

    await queue.mark_thought_done(thought.id)

    assert await queue.list_pending_thoughts("group-1") == []
