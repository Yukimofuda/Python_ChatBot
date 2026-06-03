from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from src.chatbot.bot_brain.identity.models import ResolutionResult

from .models import AliasNode


class AliasGraphRepository(Protocol):
    def upsert_alias(self, node: AliasNode) -> AliasNode:
        ...

    def list_aliases(self, identity_id: str, *, active: bool = True) -> list[AliasNode]:
        ...

    def resolve(self, alias_norm: str, scope_id: str) -> list[AliasNode]:
        ...

    def deactivate_alias(self, alias_id: str, reason: str) -> None:
        ...


def normalize_alias_value(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", "", text)
    return text.casefold()


class InMemoryAliasGraphRepository:
    """Small repository used by P1 contract tests and adapters.

    It deliberately stores typed alias nodes only. Free-form memory text is not
    indexed here, because identity resolution must not depend on arbitrary
    social memory body matches.
    """

    def __init__(self, nodes: list[AliasNode] | None = None) -> None:
        self._nodes: dict[str, AliasNode] = {}
        for node in nodes or []:
            self.upsert_alias(node)

    def upsert_alias(self, node: AliasNode) -> AliasNode:
        now = _now_iso()
        alias_id = node.alias_id or f"alias_{uuid4().hex}"
        alias_norm = node.alias_norm or normalize_alias_value(node.alias_value)
        stored = AliasNode(
            alias_id=alias_id,
            identity_id=node.identity_id,
            alias_value=node.alias_value,
            alias_norm=alias_norm,
            alias_type=node.alias_type,
            scope_id=node.scope_id,
            source_memory_id=node.source_memory_id,
            confidence=node.confidence,
            active=node.active,
            created_at=node.created_at or now,
            updated_at=now,
        )
        self._nodes[alias_id] = stored
        return stored

    def list_aliases(self, identity_id: str, *, active: bool = True) -> list[AliasNode]:
        nodes = [node for node in self._nodes.values() if node.identity_id == identity_id]
        if active:
            nodes = [node for node in nodes if node.active]
        return sorted(nodes, key=lambda node: (node.alias_type, node.alias_value))

    def resolve(self, alias_norm: str, scope_id: str) -> list[AliasNode]:
        key = normalize_alias_value(alias_norm)
        scope = str(scope_id or "").strip()
        nodes = [
            node
            for node in self._nodes.values()
            if node.alias_norm == key and (not scope or not node.scope_id or node.scope_id == scope)
        ]
        return sorted(nodes, key=lambda node: (-float(node.confidence), node.identity_id))

    def deactivate_alias(self, alias_id: str, reason: str) -> None:
        node = self._nodes[alias_id]
        self._nodes[alias_id] = AliasNode(
            alias_id=node.alias_id,
            identity_id=node.identity_id,
            alias_value=node.alias_value,
            alias_norm=node.alias_norm,
            alias_type=node.alias_type,
            scope_id=node.scope_id,
            source_memory_id=node.source_memory_id,
            confidence=node.confidence,
            active=False,
            created_at=node.created_at,
            updated_at=_now_iso(),
        )


class AliasResolver:
    def __init__(self, repository: AliasGraphRepository) -> None:
        self.repository = repository

    def resolve_alias(self, alias_norm: str, scope_id: str) -> ResolutionResult:
        nodes = [node for node in self.repository.resolve(normalize_alias_value(alias_norm), scope_id) if node.active]
        if len(nodes) == 1:
            node = nodes[0]
            return ResolutionResult(node.identity_id, node.confidence, "alias_graph")
        if len(nodes) > 1:
            return ResolutionResult(None, 0.0, "ambiguous_alias", tuple(node.identity_id for node in nodes))
        return ResolutionResult(None, 0.0, "not_found")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
