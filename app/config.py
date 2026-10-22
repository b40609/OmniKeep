import os
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    HOST: str = "0.0.0.0"
    PORT: int = 5000
    API_KEY: str = "omnifs888"
    
    # Primary LLM Configuration (OpenAI Compatible)
    PRIMARY_LLM_PROVIDER: str = "openai_compatible"
    OPENAI_BASE_URL: str = "https://platform.agnes-ai.com/v1"
    OPENAI_API_KEY: str = ""
    PRIMARY_MODEL: str = "gpt-4o"
    
    # Gemini Configuration
    GEMINI_API_KEYS_RAW: str = Field(default="", validation_alias="GEMINI_API_KEYS")
    GEMINI_MODEL: str = "gemini-2.5-flash"
    
    # Storage (Always absolute path anchored to Hub root)
    DATABASE_PATH: str = str(BASE_DIR / "omnikeep.db")

    @field_validator("DATABASE_PATH")
    @classmethod
    def resolve_db_path(cls, v: str) -> str:
        p = Path(v)
        if not p.is_absolute():
            return str((BASE_DIR / p).resolve())
        return str(p.resolve())

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def gemini_keys(self) -> List[str]:
        if not self.GEMINI_API_KEYS_RAW:
            return []
        return [k.strip() for k in self.GEMINI_API_KEYS_RAW.split(",") if k.strip()]

settings = Settings()
