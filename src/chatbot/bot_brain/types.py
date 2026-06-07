from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BrainObservation:
    text: str
    normalized_text: str
    tokens: tuple[str, ...]
    scope: str = "demo"


@dataclass(frozen=True)
class BrainMemory:
    scope: str
    topic: str
    content: str
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReplyPlan:
    intent: str
    max_length: int = 160
    requires_fallback: bool = False


@dataclass(frozen=True)
class ContextBundle:
    observation: BrainObservation
    memories: tuple[BrainMemory, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CriticResult:
    ok: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class BrainReply:
    text: str
    used_fallback: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)
