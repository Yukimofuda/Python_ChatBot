from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    bot_name: str = "Python Bot"
    owner_ids: set[str] = Field(default_factory=set)
    admin_ids: set[str] = Field(default_factory=set)
    command_start: set[str] = Field(default_factory=lambda: {"/", "!"})
    enable_calc: bool = True
    enabled_adapters: set[str] = Field(default_factory=lambda: {"onebot_v11"})
    admin_enabled: bool = True
    admin_token: str = ""
    recent_message_limit: int = 100
    data_dir: str = "data"
    max_reply_text_length: int = 1000
    auto_reply_cooldown_seconds: int = 10
    memory_max_messages_per_group: int = 200
    llm_enabled: bool = False
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_seconds: float = 20.0
    llm_max_tokens: int = 300
    llm_temperature: float = 0.7
    bilibili_enabled: bool = True
    bilibili_max_video_mb: int = 80
    bilibili_cooldown_seconds: int = 60
    bilibili_download_dir: str = "downloads/bilibili"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CHATBOT_",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> BotSettings:
    return BotSettings()
