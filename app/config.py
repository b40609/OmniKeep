import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator

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
    
    # Storage
    DATABASE_PATH: str = "omnikeep.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def gemini_keys(self) -> List[str]:
        if not self.GEMINI_API_KEYS_RAW:
            return []
        return [k.strip() for k in self.GEMINI_API_KEYS_RAW.split(",") if k.strip()]

settings = Settings()
