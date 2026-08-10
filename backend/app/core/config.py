from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    backend_host: str = "127.0.0.1"
    backend_port: int = 5001
    database_url: str = "sqlite:///./data/tarotbot.db"
    log_level: str = "INFO"
    ai_enabled: bool = True
    ai_provider: str = "fake"
    ai_chat_model: str = "gemini-2.5-flash"
    ai_conversation_prompt_version: Literal["tarotista_v1", "tarotista_v2", "tarotista_v3", "tarotista_v4"] = "tarotista_v3"
    ai_tarot_interpretation_prompt_version: Literal["tarot_interpretation_v1", "tarot_interpretation_v2"] = "tarot_interpretation_v2"
    ai_memory_model: str = "gemini-2.5-flash"
    gemini_api_key: str = ""
    groq_api_key: str = ""
    ai_timeout_seconds: int = 30
    ai_trust_env_proxy: bool = False
    ai_max_output_tokens: int = 800
    ai_recent_messages: int = 12
    ai_memory_update_interval: int = 8
    ai_store_debug_payloads: bool = False
    whatsapp_typing_chars_per_second: float = 20.0
    whatsapp_min_typing_ms: int = 1800
    whatsapp_max_typing_ms: int = 22000
    whatsapp_inter_message_delay_ms_min: int = 600
    whatsapp_inter_message_delay_ms_max: int = 1800
    admin_enabled: bool = True
    run_migrations_on_startup: bool = True

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def resolved_database_url(self) -> str:
        if self.database_url.startswith("sqlite:///./"):
            relative_path = self.database_url.removeprefix("sqlite:///./")
            return f"sqlite:///{(ROOT_DIR / relative_path).as_posix()}"
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
