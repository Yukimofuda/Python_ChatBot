from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


MemoryType = Literal["short_term", "episodic", "semantic", "reflection", "lore"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Observation:
    id: str
    group_id: str
    user_id: str
    message_id: str
    text: str
    timestamp: str
    message_type: str
    is_command: bool
    mentions_bot: bool
    features: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Memory:
    id: str
    scope: str
    scope_id: str
    type: MemoryType
    content: str
    tags: list[str]
    importance: float
    created_at: str
    last_accessed_at: str
    access_count: int
    expires_at: str | None = None


@dataclass(frozen=True)
class MoodState:
    group_id: str
    happiness: int
    tiredness: int
    curiosity: int
    teasing: int
    quietness: int
    focus: int
    updated_at: str


@dataclass(frozen=True)
class Decision:
    should_reply: bool
    reply_type: str
    reason: str
    max_length: int
    temperature: float
    memory_ids: list[str]
    safety_level: str
