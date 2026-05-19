from __future__ import annotations

from src.chatbot.shion_brain.models import MoodState, Observation, utc_now


DEFAULT_MOOD = MoodState(
    group_id="",
    happiness=42,
    tiredness=18,
    curiosity=55,
    teasing=34,
    quietness=20,
    focus=45,
    updated_at=utc_now(),
)


class MoodEngine:
    def __init__(self) -> None:
        self._states: dict[str, MoodState] = {}

    def get(self, group_id: str) -> MoodState:
        return self._states.get(group_id) or MoodState(
            group_id=group_id,
            happiness=DEFAULT_MOOD.happiness,
            tiredness=DEFAULT_MOOD.tiredness,
            curiosity=DEFAULT_MOOD.curiosity,
            teasing=DEFAULT_MOOD.teasing,
            quietness=DEFAULT_MOOD.quietness,
            focus=DEFAULT_MOOD.focus,
            updated_at=utc_now(),
        )

    def update(self, observation: Observation) -> MoodState:
        state = self.get(observation.group_id)
        happiness = state.happiness
        tiredness = state.tiredness
        curiosity = state.curiosity
        teasing = state.teasing
        quietness = state.quietness
        focus = state.focus
        if observation.is_command:
            tiredness += 2
            focus += 1
        if observation.mentions_bot:
            curiosity += 5
            quietness -= 2
        if observation.features.get("has_laugh"):
            happiness += 4
            teasing += 3
        if observation.features.get("has_question"):
            curiosity += 2
        if observation.features.get("has_distress"):
            focus += 6
            tiredness += 1
        if observation.features.get("has_sensitive"):
            focus += 8
            teasing -= 5
        updated = MoodState(
            group_id=observation.group_id,
            happiness=_clamp(happiness),
            tiredness=_clamp(tiredness),
            curiosity=_clamp(curiosity),
            teasing=_clamp(teasing),
            quietness=_clamp(quietness),
            focus=_clamp(focus),
            updated_at=utc_now(),
        )
        self._states[observation.group_id] = updated
        return updated


def _clamp(value: int) -> int:
    return max(0, min(100, int(value)))
