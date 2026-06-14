from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class CooldownManager:
    _expires_at: dict[tuple[str, str], float] = field(default_factory=dict)

    def check(
        self,
        key: str,
        *,
        user_id: str | None = None,
        group_id: str | None = None,
        seconds: float,
        scope: str = "auto",
    ) -> float:
        cooldown_key = self._make_key(key, user_id=user_id, group_id=group_id, scope=scope)
        now = time.monotonic()
        expires_at = self._expires_at.get(cooldown_key, 0)
        if expires_at > now:
            return expires_at - now
        self._expires_at[cooldown_key] = now + seconds
        self._cleanup(now)
        return 0.0

    def remaining(
        self,
        key: str,
        *,
        user_id: str | None = None,
        group_id: str | None = None,
        scope: str = "auto",
    ) -> float:
        cooldown_key = self._make_key(key, user_id=user_id, group_id=group_id, scope=scope)
        return max(0.0, self._expires_at.get(cooldown_key, 0) - time.monotonic())

    def reset(
        self,
        key: str,
        *,
        user_id: str | None = None,
        group_id: str | None = None,
        scope: str = "auto",
    ) -> None:
        self._expires_at.pop(
            self._make_key(key, user_id=user_id, group_id=group_id, scope=scope),
            None,
        )

    def _make_key(
        self,
        key: str,
        *,
        user_id: str | None,
        group_id: str | None,
        scope: str,
    ) -> tuple[str, str]:
        if scope == "global":
            return key, "global"
        if scope == "user":
            return key, f"user:{user_id or 'unknown'}"
        if scope == "group":
            return key, f"group:{group_id or 'private'}"
        if group_id:
            return key, f"group:{group_id}"
        return key, f"user:{user_id or 'unknown'}"

    def _cleanup(self, now: float) -> None:
        for key in [key for key, expires_at in self._expires_at.items() if expires_at <= now]:
            self._expires_at.pop(key, None)
