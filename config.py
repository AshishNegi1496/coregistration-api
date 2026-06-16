from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(
        default="postgresql+psycopg://postgres:admin@localhost:5432/coreg",
        alias="DATABASE_URL",
    )
    target_root: Path = Field(default=Path(r"E:\AshishWorkSpace\Coregistration-Demo\target"), alias="TARGET_ROOT")
    base_root: Path = Field(default=Path(r"E:\AshishWorkSpace\Coregistration-Demo\base"), alias="BASE_ROOT")
    output_root: Path = Field(default=Path(r"E:\AshishWorkSpace\Coregistration-Demo\output"), alias="OUTPUT_ROOT")
    staging_root: Path = Field(default=Path(r"E:\AshishWorkSpace\Coregistration-Demo\staging"), alias="STAGING_ROOT")
    log_root: Path = Field(default=Path(r"E:\AshishWorkSpace\Coregistration-Demo\logs"), alias="LOG_ROOT")
    api_key: str | None = Field(default=None, alias="API_KEY")
    geoserver_url: str = Field(default="http://localhost:8080/geoserver", alias="GEOSERVER_URL")


settings = Settings()
