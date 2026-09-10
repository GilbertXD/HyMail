import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_data_dir() -> Path:
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "HyMail"
    return Path.home() / ".hymail"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="HYMAIL_",
        extra="ignore",
    )

    app_name: str = "HyMail API"
    version: str = "0.0.1"
    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000

    data_dir: Path = Field(default_factory=default_data_dir)
    database_url: str | None = None
    api_token: str | None = None

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.database_url:
            return self.database_url

        self.data_dir.mkdir(parents=True, exist_ok=True)
        db_path = (self.data_dir / "hymail.db").as_posix()
        return f"sqlite+aiosqlite:///{db_path}"

    @property
    def migration_database_url(self) -> str:
        return self.sqlalchemy_database_url.replace("+aiosqlite", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()