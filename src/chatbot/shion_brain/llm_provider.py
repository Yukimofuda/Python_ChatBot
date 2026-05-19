from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import asyncio
import logging
import os
import re
import time
from pathlib import Path

import httpx

from src.chatbot.settings import get_settings


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMConfig:
    enabled: bool
    provider: str
    base_url: str
    api_key: str
    model: str
    api_mode: str
    timeout_seconds: float
    max_tokens: int
    temperature: float


class LLMProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_body: str = "",
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body
        self.retry_after_seconds = retry_after_seconds


def _coerce_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}


@lru_cache(maxsize=1)
def _dotenv_values() -> dict[str, str]:
    path = Path(".env")
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _env_value(key: str, default: str = "") -> str:
    return os.getenv(key) or _dotenv_values().get(key, default)


def resolve_llm_config() -> LLMConfig:
    settings = get_settings()
    api_key = _env_value("GEMINI_API_KEY") or _env_value("GOOGLE_API_KEY") or _env_value("CHATBOT_GEMINI_API_KEY")
    explicit_enabled = _coerce_bool(_env_value("CHATBOT_LLM_ENABLED"), default=settings.llm_enabled)
    enabled = explicit_enabled or bool(api_key)
    return LLMConfig(
        enabled=enabled,
        provider="gemini",
        base_url=_env_value("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"),
        api_key=api_key,
        model=_env_value("GEMINI_MODEL") or _env_value("CHATBOT_LLM_MODEL") or "gemini-2.5-flash",
        api_mode="GEMINI",
        timeout_seconds=settings.llm_timeout_seconds,
        max_tokens=max(settings.llm_max_tokens, 480),
        temperature=settings.llm_temperature,
    )


def llm_configured() -> bool:
    config = resolve_llm_config()
    return config.enabled and bool(config.api_key) and config.provider == "gemini"


class LLMProvider:
    _rate_limit_until: dict[str, float] = {}
    _unavailable_until: dict[str, float] = {}

    async def complete(self, messages: list[dict[str, str]], *, temperature: float) -> tuple[str, bool]:
        config = resolve_llm_config()
        if not config.enabled or not config.api_key:
            raise LLMProviderError("Gemini API key missing or LLM disabled")
        cooldown_key = f"{config.base_url}:{config.model}"
        self._raise_if_cooling_down(cooldown_key)
        last_error: LLMProviderError | None = None
        for attempt, delay in enumerate((0.0, 1.0, 2.5), start=1):
            if delay:
                await asyncio.sleep(delay)
            try:
                return await self._complete_gemini(config, messages, temperature=temperature)
            except LLMProviderError as exc:
                last_error = exc
                if exc.status_code == 429:
                    wait = exc.retry_after_seconds or 30.0
                    self._rate_limit_until[cooldown_key] = time.monotonic() + min(max(wait, 5.0), 120.0)
                    raise
                if exc.status_code == 503 and attempt < 3:
                    logger.warning("Gemini model unavailable, retrying attempt=%s model=%s", attempt, config.model)
                    continue
                if exc.status_code == 503:
                    self._unavailable_until[cooldown_key] = time.monotonic() + 60.0
                raise
        raise last_error or LLMProviderError("Gemini request failed")

    def _raise_if_cooling_down(self, cooldown_key: str) -> None:
        rate_remaining = self._rate_limit_until.get(cooldown_key, 0) - time.monotonic()
        if rate_remaining > 0:
            raise LLMProviderError(
                "Gemini rate limit cooldown active",
                status_code=429,
                retry_after_seconds=rate_remaining,
            )
        unavailable_remaining = self._unavailable_until.get(cooldown_key, 0) - time.monotonic()
        if unavailable_remaining > 0:
            raise LLMProviderError(
                "Gemini model unavailable cooldown active",
                status_code=503,
                retry_after_seconds=unavailable_remaining,
            )

    async def _complete_gemini(
        self,
        config: LLMConfig,
        messages: list[dict[str, str]],
        *,
        temperature: float,
    ) -> tuple[str, bool]:
        system_text = "\n\n".join(message["content"] for message in messages if message.get("role") == "system")
        user_text = "\n\n".join(message["content"] for message in messages if message.get("role") != "system")
        url = f"{config.base_url.rstrip('/')}/models/{config.model}:generateContent"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": user_text}]}],
            "generationConfig": {
                "temperature": temperature,
                "topP": 0.88,
                "maxOutputTokens": config.max_tokens,
            },
        }
        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}
        headers = {"x-goog-api-key": config.api_key, "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:2000] if exc.response is not None else ""
            retry_after = _retry_after_seconds(exc.response.headers.get("retry-after") if exc.response else None, body)
            raise LLMProviderError(
                "Gemini HTTP request failed",
                status_code=exc.response.status_code if exc.response is not None else None,
                response_body=body,
                retry_after_seconds=retry_after,
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError("Gemini HTTP transport failed") from exc

        try:
            candidates = data.get("candidates") or []
            if not candidates:
                raise LLMProviderError("Gemini response has no candidates", response_body=str(data)[:2000])
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(str(part.get("text", "")) for part in parts).strip()
        except AttributeError as exc:
            raise LLMProviderError("Gemini response format is invalid", response_body=str(data)[:2000]) from exc
        return text, not bool(text)


def _retry_after_seconds(header_value: str | None, body: str) -> float | None:
    if header_value:
        try:
            return float(header_value)
        except ValueError:
            pass
    match = re.search(r"retry in ([0-9]+(?:\.[0-9]+)?)s", body, re.I)
    if match:
        return float(match.group(1))
    return None
