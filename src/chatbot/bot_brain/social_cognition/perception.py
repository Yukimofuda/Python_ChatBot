from __future__ import annotations

from src.chatbot.bot_brain.models import Observation

from .extractor import get_mentioned_display_names, get_mentioned_user_ids, get_sender_display_name, get_sender_id


def perceive_observation(observation: Observation) -> dict[str, object]:
    return {
        "sender_id": get_sender_id(observation),
        "sender_display_name": get_sender_display_name(observation),
        "mentioned_user_ids": get_mentioned_user_ids(observation),
        "mentioned_display_names": get_mentioned_display_names(observation),
        "raw_message_text": getattr(observation, "raw_message_text", "") or getattr(observation, "text", ""),
    }
