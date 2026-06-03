from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.chatbot.bot_brain.alias_graph.repository import AliasGraphRepository, normalize_alias_value
from src.chatbot.bot_brain.prompting.persona_context import RenderableFact, sanitize_persona_text
from src.chatbot.bot_brain.social_arch.memory.models import MemoryRecord
from src.chatbot.bot_brain.social_arch.memory.service import MemorySelector


class ShadowMemoryRepository(Protocol):
    def retrieve(self, selector: MemorySelector) -> list[MemoryRecord]:
        ...


@dataclass(frozen=True)
class ShadowRetrievalReport:
    query_text: str
    identity_id: str | None
    legacy_hit_count: int
    shadow_hit_count: int
    legacy_rendered_preview: str
    shadow_renderable_facts: tuple[RenderableFact, ...]
    mismatches: tuple[str, ...]
    safe_for_cutover: bool
    reason: str = ""


class ShadowRetriever:
    """Shadow compare retrieval without changing production routing."""

    def __init__(self, memory_repository: ShadowMemoryRepository, alias_repository: AliasGraphRepository) -> None:
        self.memory_repository = memory_repository
        self.alias_repository = alias_repository

    def compare(
        self,
        *,
        query_text: str,
        scope_id: str = "",
        identity_id: str | None = None,
        alias_text: str = "",
        legacy_rendered_preview: str = "",
        legacy_hit_count: int = 0,
    ) -> ShadowRetrievalReport:
        resolved_identity = identity_id
        reason = "resolved_identity" if identity_id else ""
        mismatches: list[str] = []

        if not resolved_identity and alias_text:
            nodes = [node for node in self.alias_repository.resolve(normalize_alias_value(alias_text), scope_id) if node.active]
            if len(nodes) > 1:
                return self._unresolved(query_text, legacy_rendered_preview, legacy_hit_count, "ambiguous_alias")
            if not nodes:
                return self._unresolved(query_text, legacy_rendered_preview, legacy_hit_count, "unresolved_alias")
            resolved_identity = nodes[0].identity_id
            reason = "alias_graph"

        if not resolved_identity:
            return self._unresolved(query_text, legacy_rendered_preview, legacy_hit_count, "unresolved_identity")

        records = self.memory_repository.retrieve(MemorySelector(identity_id=resolved_identity, scope_id=scope_id or None, active=True))
        facts = tuple(_record_to_fact(record) for record in records if _record_to_fact(record).value_text)
        if legacy_hit_count != len(facts):
            mismatches.append(f"hit_count legacy={legacy_hit_count} shadow={len(facts)}")
        if not facts:
            reason = "known_identity_no_facts"
        return ShadowRetrievalReport(
            query_text=query_text,
            identity_id=resolved_identity,
            legacy_hit_count=legacy_hit_count,
            shadow_hit_count=len(facts),
            legacy_rendered_preview=legacy_rendered_preview,
            shadow_renderable_facts=facts,
            mismatches=tuple(mismatches),
            safe_for_cutover=bool(facts and not mismatches),
            reason=reason,
        )

    @staticmethod
    def _unresolved(query_text: str, legacy_preview: str, legacy_hit_count: int, reason: str) -> ShadowRetrievalReport:
        return ShadowRetrievalReport(
            query_text=query_text,
            identity_id=None,
            legacy_hit_count=legacy_hit_count,
            shadow_hit_count=0,
            legacy_rendered_preview=legacy_preview,
            shadow_renderable_facts=(),
            mismatches=(reason,),
            safe_for_cutover=False,
            reason=reason,
        )


def _record_to_fact(record: MemoryRecord) -> RenderableFact:
    text = sanitize_persona_text(record.value_text)
    return RenderableFact(record.predicate, text, record.render_policy)
