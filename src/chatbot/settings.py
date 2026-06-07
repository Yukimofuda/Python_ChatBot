from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    bot_name: str = Field(
        default="PythonBot",
        validation_alias=AliasChoices("BOT_NICKNAME", "CHATBOT_BOT_NAME"),
    )
    admin_ids: set[str] = Field(
        default_factory=set,
        validation_alias=AliasChoices("ADMIN_IDS", "CHATBOT_ADMIN_IDS"),
    )
    command_start: set[str] = Field(default_factory=lambda: {"/", "!"})
    enable_calc: bool = True
    enabled_adapters: set[str] = Field(default_factory=lambda: {"onebot_v11"})
    admin_enabled: bool = True
    admin_token: str = Field(
        default="",
        validation_alias=AliasChoices("ADMIN_TOKEN", "CHATBOT_ADMIN_TOKEN"),
    )
    recent_message_limit: int = 40
    data_dir: str = Field(
        default="data",
        validation_alias=AliasChoices("DATA_DIR", "CHATBOT_DATA_DIR"),
    )
    max_reply_text_length: int = 1000
    auto_reply_cooldown_seconds: int = 10
    memory_max_messages_per_scope: int = 120
    llm_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("LLM_ENABLED", "CHATBOT_LLM_ENABLED"),
    )
    llm_base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias=AliasChoices("OPENAI_BASE_URL", "CHATBOT_LLM_BASE_URL"),
    )
    llm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("OPENAI_API_KEY", "CHATBOT_LLM_API_KEY"),
    )
    llm_model: str = Field(
        default="gpt-4o-mini",
        validation_alias=AliasChoices("OPENAI_MODEL", "CHATBOT_LLM_MODEL"),
    )
    llm_timeout_seconds: float = 20.0
    llm_max_tokens: int = 480
    llm_temperature: float = 0.3
    bilibili_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("BILIBILI_ENABLED", "CHATBOT_BILIBILI_ENABLED"),
    )
    bilibili_max_video_mb: int = 80
    bilibili_cooldown_seconds: int = 60
    bilibili_download_dir: str = "downloads/bilibili"
    bilibili_cookie_file: str = Field(
        default="",
        validation_alias=AliasChoices("BILIBILI_COOKIE_FILE", "CHATBOT_BILIBILI_COOKIE_FILE"),
    )
    onebot_ws_url: str = Field(
        default="ws://127.0.0.1:8080/onebot/v11/ws",
        validation_alias=AliasChoices("ONEBOT_WS_URL", "CHATBOT_ONEBOT_WS_URL"),
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> BotSettings:
    return BotSettings()
