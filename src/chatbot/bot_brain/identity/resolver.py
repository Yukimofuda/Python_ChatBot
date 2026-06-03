from __future__ import annotations

from typing import Protocol

from .models import Identity, ResolutionResult


class IdentityRepository(Protocol):
    def get_by_internal_key(self, platform: str, internal_user_key: str) -> Identity | None:
        ...

    def get(self, identity_id: str) -> Identity | None:
        ...


class InMemoryIdentityRepository:
    def __init__(self, identities: list[Identity] | None = None) -> None:
        self._by_id: dict[str, Identity] = {}
        self._by_key: dict[tuple[str, str], Identity] = {}
        for identity in identities or []:
            self.upsert(identity)

    def upsert(self, identity: Identity) -> Identity:
        self._by_id[identity.identity_id] = identity
        self._by_key[(identity.platform, identity.internal_user_key)] = identity
        return identity

    def get_by_internal_key(self, platform: str, internal_user_key: str) -> Identity | None:
        return self._by_key.get((str(platform), str(internal_user_key)))

    def get(self, identity_id: str) -> Identity | None:
        return self._by_id.get(str(identity_id))


class IdentityResolver:
    def __init__(self, repository: IdentityRepository) -> None:
        self.repository = repository

    def resolve_internal_key(self, platform: str, internal_user_key: str) -> ResolutionResult:
        identity = self.repository.get_by_internal_key(platform, internal_user_key)
        if identity is None:
            return ResolutionResult(None, 0.0, "not_found")
        return ResolutionResult(identity.identity_id, 1.0, "internal_key")
