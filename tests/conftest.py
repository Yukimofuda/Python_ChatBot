from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_runtime_env(monkeypatch):
    monkeypatch.setenv("CHATBOT_TESTING", "true")
    for key in (
        "CHATBOT_LLM_ENABLED",
        "CHATBOT_LLM_API_KEY",
        "CHATBOT_LLM_BASE_URL",
        "CHATBOT_LLM_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)

    from src.chatbot.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
