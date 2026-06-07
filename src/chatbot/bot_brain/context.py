from __future__ import annotations

from src.chatbot.bot_brain.types import BrainObservation, BrainMemory, ContextBundle


def build_context(
    observation: BrainObservation,
    memories: tuple[BrainMemory, ...],
) -> ContextBundle:
    notes: list[str] = []
    if memories:
        notes.append("retrieved_demo_memory")
    if len(observation.tokens) > 16:
        notes.append("long_input")
    return ContextBundle(observation=observation, memories=memories, notes=tuple(notes))
