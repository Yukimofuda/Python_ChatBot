from __future__ import annotations

import logging

import httpx

from src.chatbot.settings import get_settings


logger = logging.getLogger(__name__)


async def chat_completion(messages: list[dict[str, str]]) -> str | None:
    settings = get_settings()
    if not settings.llm_enabled or not settings.llm_api_key:
        return None

    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": settings.llm_temperature,
        "max_tokens": settings.llm_max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
    except Exception:
        logger.exception("LLM chat completion failed")
        return None

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        logger.warning("Unexpected LLM response shape: %s", data)
        return None
    return str(content).strip() or None
