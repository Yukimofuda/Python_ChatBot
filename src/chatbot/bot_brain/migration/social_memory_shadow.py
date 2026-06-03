from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.chatbot.bot_brain.alias_graph.models import AliasNode
from src.chatbot.bot_brain.alias_graph.sqlite_repository import SQLiteAliasGraphRepository
from src.chatbot.bot_brain.social_arch.memory.models import MemoryRecord
from src.chatbot.bot_brain.social_arch.memory.sqlite_repository import SQLiteSocialMemoryRepository


@dataclass(frozen=True)
class SocialMemoryShadowSnapshot:
    memories: tuple[MemoryRecord, ...]
    aliases: tuple[AliasNode, ...]


class SocialMemoryShadowReader:
    """Read legacy social memory data through P1 models without migration."""

    def __init__(self, legacy_db_path: str | Path) -> None:
        self.legacy_db_path = Path(legacy_db_path)

    def snapshot(self) -> SocialMemoryShadowSnapshot:
        memory_repo = SQLiteSocialMemoryRepository(self.legacy_db_path)
        alias_repo = SQLiteAliasGraphRepository(self.legacy_db_path)
        return SocialMemoryShadowSnapshot(
            memories=tuple(memory_repo.shadow_read_legacy()),
            aliases=tuple(alias_repo.shadow_read_legacy()),
        )
