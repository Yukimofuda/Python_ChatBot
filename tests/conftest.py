from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_runtime_env(monkeypatch):
    monkeypatch.setenv("CHATBOT_TESTING", "true")
    for key in (
        "LLM_ENABLED",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)

    from src.chatbot.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
