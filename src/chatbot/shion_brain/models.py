from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


MemoryType = Literal["short_term", "episodic", "semantic", "reflection", "lore"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_now_iso() -> str:
    return utc_now()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


MemoryScope = Literal["global", "group", "user", "topic"]
SemanticObjectType = Literal["entity", "attribute", "preference", "belief", "style", "risk", "project"]
ProceduralOutcome = Literal["success", "failure", "neutral"]
ReflectionType = Literal["prospective", "retrospective", "consolidation"]
ReplyIntent = Literal[
    "answer",
    "comfort",
    "tease",
    "ask_clarification",
    "repair",
    "remember",
    "stay_silent",
    "inspire",
    "challenge",
    "synthesize",
]
AgendaStatus = Literal["active", "completed", "abandoned"]


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
    motivation_score: float = 0.0
    meta_motivation_score: float = 0.0
    reply_intent: str = "answer"
    internal_notes: list[str] = field(default_factory=list)
    allowed_actions: list[str] = field(default_factory=list)
    incubation_required: bool = False
    incubation_reason: str = ""


@dataclass(slots=True)
class SemanticEdge:
    id: str
    scope: MemoryScope
    scope_id: str
    subject: str
    relation: str
    object_value: str
    object_type: SemanticObjectType = "attribute"
    confidence: float = 0.5
    evidence_refs: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    conflict_group: str | None = None
    is_active: bool = True
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    expires_at: str | None = None

    def clamp(self) -> "SemanticEdge":
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        return self

    def to_json_fields(self) -> dict[str, str]:
        return {
            "evidence_refs": json.dumps(self.evidence_refs, ensure_ascii=False),
            "tags": json.dumps(self.tags, ensure_ascii=False),
        }


@dataclass(slots=True)
class ProceduralPrompt:
    id: str
    scope_id: str
    user_id: str | None
    context_signature: str
    style_hint: str
    prompt_delta: str
    success_score: float = 0.0
    failure_score: float = 0.0
    evidence_count: int = 0
    last_outcome: ProceduralOutcome = "neutral"
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    @property
    def effectiveness(self) -> float:
        total = self.success_score + self.failure_score + 1e-6
        return self.success_score / total


@dataclass(slots=True)
class BeliefHypothesis:
    id: str
    scope_id: str
    subject: str
    hypothesis: str
    probability: float
    evidence_refs: list[str] = field(default_factory=list)
    uncertainty_note: str = ""
    updated_at: str = field(default_factory=utc_now_iso)

    def clamp(self) -> "BeliefHypothesis":
        self.probability = max(0.0, min(1.0, float(self.probability)))
        return self


@dataclass(slots=True)
class DistilledMemory:
    id: str
    scope_id: str
    reflection_type: ReflectionType
    summary: str
    semantic_edges: list[SemanticEdge] = field(default_factory=list)
    belief_updates: list[BeliefHypothesis] = field(default_factory=list)
    procedural_updates: list[ProceduralPrompt] = field(default_factory=list)
    stale_memory_ids: list[str] = field(default_factory=list)
    surprise_score: float = 0.0
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class CognitiveDecisionPatch:
    motivation_score: float = 0.0
    meta_motivation_score: float = 0.0
    reply_intent: ReplyIntent = "stay_silent"
    internal_notes: list[str] = field(default_factory=list)
    allowed_actions: list[str] = field(default_factory=list)
    incubation_required: bool = False
    incubation_reason: str = ""
    semantic_memory_ids: list[str] = field(default_factory=list)
    procedural_memory_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AgendaItem:
    id: str
    scope_id: str
    target_user_id: str | None
    goal_type: str
    description: str
    priority: float
    status: AgendaStatus = "active"
    metrics_trigger: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def clamp(self) -> "AgendaItem":
        self.priority = max(0.0, min(1.0, float(self.priority)))
        return self
