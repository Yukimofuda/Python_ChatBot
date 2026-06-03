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
    sender_id: str = ""
    sender_display_name: str = ""
    mentioned_display_names: dict[str, str] = field(default_factory=dict)
    raw_message_text: str = ""
    mentioned_user_ids: list[str] = field(default_factory=list)
    primary_target_user_id: str | None = None
    mentioned_user_display_names: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Backward/forward compatibility: older code used
        # mentioned_user_display_names; newer tests/plugins use
        # mentioned_display_names. Observation is frozen, so use
        # object.__setattr__.
        if not self.sender_id:
            object.__setattr__(
                self,
                "sender_id",
                str(self.features.get("sender_id", self.user_id)) if isinstance(self.features, dict) else str(self.user_id),
            )
        if not self.raw_message_text:
            object.__setattr__(
                self,
                "raw_message_text",
                str(self.features.get("raw_message_text", self.text)) if isinstance(self.features, dict) else str(self.text),
            )
        if not self.sender_display_name:
            object.__setattr__(
                self,
                "sender_display_name",
                str(self.features.get("sender_display_name", "")) if isinstance(self.features, dict) else "",
            )
        if not self.mentioned_user_ids and isinstance(self.features, dict):
            ids = self.features.get("mentioned_user_ids") or []
            object.__setattr__(self, "mentioned_user_ids", list(ids))
        if self.primary_target_user_id is None and self.mentioned_user_ids:
            object.__setattr__(self, "primary_target_user_id", self.mentioned_user_ids[0])
        if not self.mentioned_display_names and self.mentioned_user_display_names:
            object.__setattr__(self, "mentioned_display_names", dict(self.mentioned_user_display_names))
        if not self.mentioned_user_display_names and self.mentioned_display_names:
            object.__setattr__(self, "mentioned_user_display_names", dict(self.mentioned_display_names))
        if not self.mentioned_display_names and isinstance(self.features, dict):
            names = self.features.get("mentioned_display_names") or self.features.get("mentioned_user_display_names") or {}
            object.__setattr__(self, "mentioned_display_names", dict(names))
            object.__setattr__(self, "mentioned_user_display_names", dict(names))


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


# ---------------------------------------------------------------------------
# Compatibility model restored by tools/repair_models_imports.py
#
# A previous group-user-memory patch accidentally replaced models.py with a
# trimmed version. Newer memory_store.py imports AgendaItem, so test collection
# fails before any real test runs. This class is deliberately permissive: it
# accepts both the known agenda fields and forward-compatible keyword fields.
# ---------------------------------------------------------------------------
@dataclass(init=False)
class AgendaItem:
    id: str = ""
    scope_id: str = ""
    group_id: str = ""
    user_id: str | None = None
    title: str = ""
    content: str = ""
    description: str = ""
    kind: str = ""
    status: str = "active"
    priority: float = 0.0
    reason: str = ""
    source: str = ""
    source_memory_id: str | None = None
    evidence_refs: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5
    is_active: bool = True
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    due_at: str | None = None
    next_run_at: str | None = None
    last_run_at: str | None = None
    expires_at: str | None = None
    target_user_id: str | None = None
    goal_type: str = ""
    metrics_trigger: dict[str, Any] = field(default_factory=dict)
    completed_at: str | None = None

    def __init__(self, **kwargs: Any) -> None:
        defaults = {
            "id": "",
            "scope_id": "",
            "group_id": "",
            "user_id": None,
            "title": "",
            "content": "",
            "description": "",
            "kind": "",
            "status": "active",
            "priority": 0.0,
            "reason": "",
            "source": "",
            "source_memory_id": None,
            "evidence_refs": [],
            "tags": [],
            "payload": {},
            "metadata": {},
            "confidence": 0.5,
            "is_active": True,
            "created_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
            "due_at": None,
            "next_run_at": None,
            "last_run_at": None,
            "expires_at": None,
        }
        defaults.update(kwargs)
        # Previous compatibility stubs used pending, which makes has_active_agenda false.
        if not defaults.get("status") or defaults.get("status") == "pending":
            defaults["status"] = "active"
        defaults["is_active"] = bool(defaults.get("is_active", True))
        for key, value in defaults.items():
            setattr(self, key, value)

    def clamp(self) -> "AgendaItem":
        self.priority = max(0.0, min(1.0, float(self.priority)))
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        return self
