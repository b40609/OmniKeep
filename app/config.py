import os
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    HOST: str = "0.0.0.0"
    PORT: int = 5000
    API_KEY: str = ""
    CORS_ORIGINS: List[str] = []
    BACKGROUND_SERVICES_ENABLED: bool = True
    
    # Primary LLM Configuration (Agnes AI 3.0 OpenAI-Compatible Endpoint)
    PRIMARY_LLM_PROVIDER: str = "openai_compatible"
    OPENAI_BASE_URL: str = "https://platform.agnes-ai.com/v1"
    OPENAI_API_KEY: str = ""
    PRIMARY_MODEL: str = "agnes-3.0-flash"
    
    # Gemini Configuration
    GEMINI_API_KEYS_RAW: str = Field(default="", validation_alias="GEMINI_API_KEYS")
    GEMINI_MODEL: str = "gemini-2.5-flash"
    
    # Storage (Always absolute path anchored to Hub root)
    DATABASE_PATH: str = str(BASE_DIR / "omnikeep.db")

    # Browser Session & Cookie Bridge Configuration
    BROWSER_COOKIE_SOURCE: str = "chrome"
    BROWSER_COOKIE_FILE: str = "cookies.txt"
    # CDP bridge: Chrome 127+ App-Bound Encryption + DB file lock make yt-dlp
    # live extraction impossible, so we fetch decrypted cookies over the
    # DevTools protocol from a dedicated automation profile instead.
    BROWSER_CDP_PORT: int = 9222
    BROWSER_CDP_PROFILE_DIR: str = str(Path.home() / "AppData" / "Local" / "OmniKeep" / "chrome-cdp")
    BROWSER_CDP_AUTOLAUNCH: bool = True

    # Telegram Bot Configuration
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_ALLOWED_USER_IDS_RAW: str = Field(default="", validation_alias="TELEGRAM_ALLOWED_USER_IDS")

    # Radar Engine Configuration
    RADAR_ENABLED: bool = True
    RADAR_INTERVAL_SECONDS: int = 300
    GITHUB_TOKEN: str = ""

    # Multi-sink backup (self-hosters pick their own: local folder / rclone cloud / git repo)
    BACKUP_SINK: str = "local"          # local | rclone | git | off
    BACKUP_DIR: str = str(BASE_DIR / "backups")
    BACKUP_KEEP: int = 14               # rotating local snapshots to keep
    BACKUP_RCLONE_REMOTE: str = ""      # e.g. "gdrive:OmniKeep"
    BACKUP_GIT_REPO_DIR: str = ""       # local clone of a private repo to auto-commit into
    BACKUP_HOUR: int = 4                # daily backup window (local time)

    # LLM rate-limit protection (client-side pacing shared by all callers).
    # Agnes 3.0 Flash is priced at $0 (unlimited tokens) but free-tier API keys
    # carry a low requests-per-minute ceiling — pace conservatively by default
    # and let the adaptive limiter ease off when the account allows more.
    LLM_MIN_REQUEST_INTERVAL: float = 2.5   # seconds between request starts (≈24 RPM); adapts up on 429
    LLM_MAX_CONCURRENCY: int = 2            # parallel in-flight LLM calls

    # LINE Messaging API Configuration
    LINE_CHANNEL_SECRET: str = ""
    LINE_CHANNEL_ACCESS_TOKEN: str = ""
    LINE_ALLOWED_USER_IDS_RAW: str = Field(default="", validation_alias="LINE_ALLOWED_USER_IDS")

    @field_validator("DATABASE_PATH")
    @classmethod
    def resolve_db_path(cls, v: str) -> str:
        p = Path(v)
        if not p.is_absolute():
            return str((BASE_DIR / p).resolve())
        return str(p.resolve())

    @field_validator("BROWSER_COOKIE_FILE")
    @classmethod
    def resolve_cookie_file(cls, v: str) -> str:
        if not v:
            return ""
        p = Path(v)
        if not p.is_absolute():
            return str((BASE_DIR / p).resolve())
        return str(p.resolve())

    model_config = SettingsConfigDict(
        env_file=None if os.environ.get("OMNIKEEP_TESTING") == "1" else str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def gemini_keys(self) -> List[str]:
        if not self.GEMINI_API_KEYS_RAW:
            return []
        return [k.strip() for k in self.GEMINI_API_KEYS_RAW.split(",") if k.strip()]

    @property
    def telegram_allowed_ids(self) -> List[int]:
        if not self.TELEGRAM_ALLOWED_USER_IDS_RAW:
            return []
        res = []
        for x in self.TELEGRAM_ALLOWED_USER_IDS_RAW.split(","):
            s = x.strip()
            if s.lstrip("-").isdigit():
                res.append(int(s))
        return res

    @property
    def line_allowed_ids(self) -> List[str]:
        if not self.LINE_ALLOWED_USER_IDS_RAW:
            return []
        return [x.strip() for x in self.LINE_ALLOWED_USER_IDS_RAW.split(",") if x.strip()]

    @property
    def has_cookie_file(self) -> bool:
        return bool(self.BROWSER_COOKIE_FILE and Path(self.BROWSER_COOKIE_FILE).is_file())

settings = Settings()
