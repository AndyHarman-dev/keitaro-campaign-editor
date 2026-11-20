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
    keitaro_fake: bool = Field(
        default=False, description="Use the in-process fake tracker (demos and e2e; no key needed)")
    keitaro_fake_state: Path | None = Field(
        default=None, description="Fake mode: JSON file the fake tracker is saved to and loaded from")
    allowed_hosts: list[str] = Field(
        default=["localhost", "127.0.0.1"],
        description="Host names the API answers to; add a LAN address to open it from another device")

    @property
    def keitaro_configured(self) -> bool:
        return self.keitaro_fake or bool(
            self.keitaro_base_url and self.keitaro_api_key.get_secret_value())

    @property
    def tracker_host(self) -> str:
        return self.keitaro_base_url.rstrip("/").removesuffix("/admin")

    def campaign_admin_url(self, campaign_id: int) -> str:
        """Link to the campaign in Keitaro's admin UI ("View in KT")."""
        return f"{self.tracker_host}/admin/#!/campaigns/{campaign_id}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
