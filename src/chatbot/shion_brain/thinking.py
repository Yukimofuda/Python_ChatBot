from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar


T = TypeVar("T")
THINKING_HINTS = (
    "等我组织一下语言。",
    "我想一下怎么说更合适。",
    "嗯……这个我认真想想。",
)


async def with_delayed_thinking(
    awaitable: Awaitable[T],
    send_hint: Callable[[str], Awaitable[object]],
    *,
    delay_seconds: float = 2.0,
) -> T:
    task = asyncio.create_task(awaitable)
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=delay_seconds)
    except TimeoutError:
        await send_hint(random.choice(THINKING_HINTS))
        return await task
