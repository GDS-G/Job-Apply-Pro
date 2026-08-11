from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated local runtime configuration."""

    model_config = SettingsConfigDict(
        env_prefix="JAP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8765, ge=1024, le=65535)
    database_url: str = "sqlite:///./var/job_apply_pro.db"
    log_level: str = "INFO"
    automation_enabled: bool = False
    api_token: SecretStr | None = None
    browser_data_dir: Path = Path("./var/browser")
    browser_artifact_dir: Path = Path("./var/browser-artifacts")
    browser_headless: bool = True

    def ensure_runtime_directories(self) -> None:
        if self.database_url.startswith("sqlite:///./"):
            database_path = Path(self.database_url.removeprefix("sqlite:///./"))
            database_path.parent.mkdir(parents=True, exist_ok=True)
        self.browser_data_dir.mkdir(parents=True, exist_ok=True)
        self.browser_artifact_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
