from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://vero:vero@localhost:5433/vero"

    llm_provider: Literal["fake", "openai"] = "fake"
    document_extractor: Literal["fake", "openai"] = "fake"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    storage_dir: str = "./storage"

    llm_timeout_seconds: float = 30.0
    tool_timeout_seconds: float = 10.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
