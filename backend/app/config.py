from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime settings, read from the repo-root .env (gitignored)."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    keitaro_base_url: str = Field(default="", description="Tracker host, no /admin_api suffix")
    keitaro_api_key: SecretStr = Field(default=SecretStr(""))
    keitaro_default_domain: str = Field(default="", description="Domain name, e.g. track.example.com")
    keitaro_default_group: str = Field(default="", description="Campaign group name")
    keitaro_default_source: str = Field(default="", description="Traffic source name")
    database_url: str = f"sqlite:///{REPO_ROOT / 'data' / 'app.db'}"

    @property
    def keitaro_api_root(self) -> str:
        return self.keitaro_base_url.rstrip("/") + "/admin_api/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
