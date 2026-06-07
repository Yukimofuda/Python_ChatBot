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
        actor_key: str | None = None,
        room_key: str | None = None,
        seconds: float,
        scope: str = "auto",
    ) -> float:
        cooldown_key = self._make_key(key, actor_key=actor_key, room_key=room_key, scope=scope)
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
        actor_key: str | None = None,
        room_key: str | None = None,
        scope: str = "auto",
    ) -> float:
        cooldown_key = self._make_key(key, actor_key=actor_key, room_key=room_key, scope=scope)
        return max(0.0, self._expires_at.get(cooldown_key, 0) - time.monotonic())

    def reset(
        self,
        key: str,
        *,
        actor_key: str | None = None,
        room_key: str | None = None,
        scope: str = "auto",
    ) -> None:
        self._expires_at.pop(
            self._make_key(key, actor_key=actor_key, room_key=room_key, scope=scope),
            None,
        )

    def _make_key(
        self,
        key: str,
        *,
        actor_key: str | None,
        room_key: str | None,
        scope: str,
    ) -> tuple[str, str]:
        if scope == "global":
            return key, "global"
        if scope == "actor":
            return key, actor_key or "actor-unknown"
        if scope == "room":
            return key, room_key or "private"
        if room_key:
            return key, room_key
        return key, actor_key or "actor-unknown"

    def _cleanup(self, now: float) -> None:
        for key in [key for key, expires_at in self._expires_at.items() if expires_at <= now]:
            self._expires_at.pop(key, None)
