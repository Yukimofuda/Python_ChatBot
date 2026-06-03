from __future__ import annotations

from typing import Protocol


class ReplyOrchestrator(Protocol):
    async def generate(self, context_bundle: object) -> str:
        ...

