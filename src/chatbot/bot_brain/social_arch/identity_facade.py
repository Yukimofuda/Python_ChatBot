from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.chatbot.bot_brain.alias_graph.repository import AliasResolver, normalize_alias_value
from src.chatbot.bot_brain.identity.models import Identity, ResolutionResult
from src.chatbot.bot_brain.identity.resolver import IdentityResolver


@dataclass(frozen=True)
class ResolvedIdentity:
    result: ResolutionResult
    identity: Identity | None = None
    display_name: str = ""


class SocialIdentityFacade:
    """P1 identity entrypoint for sender, mention, reply target, and alias text.

    The facade keeps identity resolution ahead of memory retrieval. It can be
    backed by the new repositories or by the typed legacy alias-name index.
    """

    def __init__(
        self,
        *,
        identity_resolver: IdentityResolver | None = None,
        alias_resolver: AliasResolver | None = None,
        identity_repository: Any | None = None,
        legacy_store: Any | None = None,
        platform: str = "qq",
    ) -> None:
        self.identity_resolver = identity_resolver
        self.alias_resolver = alias_resolver
        self.identity_repository = identity_repository
        self.legacy_store = legacy_store
        self.platform = platform

    def resolve_sender(self, observation: Any) -> ResolvedIdentity:
        key = _first_attr(observation, "sender_user_id", "user_id", "sender_id")
        return self.resolve_internal_key(key)

    def resolve_mention(self, observation: Any, mentioned_key: str | None = None) -> ResolvedIdentity:
        key = mentioned_key
        if key is None:
            mentioned = list(_first_attr(observation, "mentioned_user_ids", default=()) or ())
            key = str(mentioned[0]) if mentioned else ""
        return self.resolve_internal_key(key)

    def resolve_reply_target(self, observation: Any) -> ResolvedIdentity:
        key = _first_attr(observation, "reply_user_id", "reply_to_user_id", "quoted_user_id")
        return self.resolve_internal_key(key)

    def resolve_internal_key(self, internal_user_key: Any) -> ResolvedIdentity:
        key = str(internal_user_key or "").strip()
        if not key:
            return ResolvedIdentity(ResolutionResult(None, 0.0, "missing_internal_key"))
        if self.identity_resolver is None:
            identity = None
            if self.identity_repository is not None:
                identity = self.identity_repository.get_by_internal_key(self.platform, key)
            if identity is None:
                identity = Identity(
                    identity_id=key,
                    platform=self.platform,
                    internal_user_key=key,
                    display_name="",
                    status="active",
                    created_at="",
                    updated_at="",
                )
            return ResolvedIdentity(ResolutionResult(identity.identity_id, 1.0, "internal_key"), identity, identity.display_name)
        result = self.identity_resolver.resolve_internal_key(self.platform, key)
        identity = self._identity(result.identity_id)
        return ResolvedIdentity(result, identity, identity.display_name if identity else "")

    def resolve_alias(self, alias_text: str, *, scope_id: str = "") -> ResolvedIdentity:
        if self.alias_resolver is not None:
            result = self.alias_resolver.resolve_alias(normalize_alias_value(alias_text), scope_id)
            identity = self._identity(result.identity_id)
            return ResolvedIdentity(result, identity, identity.display_name if identity else "")
        if self.legacy_store is not None:
            return self._resolve_legacy_alias(alias_text, scope_id=scope_id)
        return ResolvedIdentity(ResolutionResult(None, 0.0, "alias_resolver_unavailable"))

    def _resolve_legacy_alias(self, alias_text: str, *, scope_id: str = "") -> ResolvedIdentity:
        from src.chatbot.bot_brain.social_cognition.alias_name_index import search_alias_name_index

        candidates = search_alias_name_index(self.legacy_store, [alias_text], scope_id=scope_id, top_k=8)
        if len(candidates) == 1:
            candidate = candidates[0]
            identity = Identity(
                identity_id=candidate.user_id,
                platform=self.platform,
                internal_user_key=candidate.user_id,
                display_name=candidate.display_name,
                status="active",
                created_at="",
                updated_at=candidate.updated_at,
            )
            return ResolvedIdentity(
                ResolutionResult(candidate.user_id, float(candidate.confidence), "legacy_typed_alias_index"),
                identity,
                candidate.display_name or candidate.label,
            )
        if len(candidates) > 1:
            return ResolvedIdentity(
                ResolutionResult(None, 0.0, "ambiguous_alias", tuple(c.user_id for c in candidates)),
            )
        return ResolvedIdentity(ResolutionResult(None, 0.0, "not_found"))

    def _identity(self, identity_id: str | None) -> Identity | None:
        if not identity_id or self.identity_repository is None:
            return None
        return self.identity_repository.get(identity_id)


def _first_attr(obj: Any, *names: str, default: Any = "") -> Any:
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value not in (None, ""):
                return value
        if isinstance(obj, dict) and obj.get(name) not in (None, ""):
            return obj.get(name)
    return default
