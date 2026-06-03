from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GovernanceDecision:
    allowed: bool
    reason: str
    risk_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeletionPlan:
    selector: str
    candidate_ids: tuple[str, ...]
    reason: str
    requires_confirmation: bool = True


class MemoryGovernanceService(Protocol):
    def validate_write(self, candidate: object) -> GovernanceDecision:
        ...

    def classify_read(self, request: object) -> GovernanceDecision:
        ...

    def plan_delete(self, selector: object) -> DeletionPlan:
        ...

    def rollback_policy(self, action: object) -> GovernanceDecision:
        ...

    def privacy_policy(self, audience: str) -> GovernanceDecision:
        ...

