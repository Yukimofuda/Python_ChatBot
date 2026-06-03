from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    identity_id: str
    platform: str
    internal_user_key: str
    display_name: str
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ResolutionResult:
    identity_id: str | None
    confidence: float
    matched_by: str
    candidates: tuple[str, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.identity_id is not None and self.confidence > 0.0

