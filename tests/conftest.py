from __future__ import annotations

import pytest


LLM_ENV_KEYS = (
    "CHATBOT_LLM_PROVIDER",
    "AI_API_MODE",
    "CHATBOT_LLM_ENABLED",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "OPENAI_BASE_URL",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "GEMINI_API_URL",
    "GEMINI_BASE_URL",
    "GOOGLE_API_KEY",
    "CHATBOT_GEMINI_API_KEY",
    "CHATBOT_LLM_MODEL",
)


@pytest.fixture(autouse=True)
def isolate_llm_env(monkeypatch):
    """Keep unit tests from reading the developer's real LLM configuration.

    Tests may still opt into a provider by setting variables with monkeypatch.
    Real bot runtime is unaffected because CHATBOT_TESTING is only set here.
    """
    monkeypatch.setenv("CHATBOT_TESTING", "true")
    for key in LLM_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    _clear_llm_caches()
    yield
    _clear_llm_caches()


def _clear_llm_caches() -> None:
    try:
        from src.chatbot.settings import get_settings
        get_settings.cache_clear()
    except Exception:
        pass

    try:
        from src.chatbot.config import get_settings as legacy_get_settings
        legacy_get_settings.cache_clear()
    except Exception:
        pass

    try:
        from src.chatbot.bot_brain.llm_provider import _dotenv_values
        _dotenv_values.cache_clear()
    except Exception:
        pass
