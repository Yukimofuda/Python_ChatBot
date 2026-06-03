from __future__ import annotations

from src.chatbot.bot_brain.models import Observation

from .retriever import SocialRetriever
from .store import SocialCognitionStore, social_cognition_store


def build_social_context(observation: Observation, *, store: SocialCognitionStore | None = None, record: bool = True) -> str:
    backend = store or social_cognition_store
    if record:
        backend.record_observation(observation)
    return SocialRetriever(backend).retrieve_for_observation(observation).context
