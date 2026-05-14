from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    bot_name: str = "CrossBot"
    owner_ids: set[str] = Field(default_factory=set)
    command_start: set[str] = Field(default_factory=lambda: {"/", "!"})
    enable_calc: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CHATBOT_",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> BotSettings:
    return BotSettings()
