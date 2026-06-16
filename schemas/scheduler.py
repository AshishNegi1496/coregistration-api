from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class WatchFolderRequest(BaseModel):
    path: str
    recursive: bool = True
    sensor_hint: str | None = None


class SchedulerConfigRequest(BaseModel):
    folders: list[WatchFolderRequest]
    interval_minutes: int = Field(15, ge=1)
    min_overlap_pct: float = Field(10.0, ge=0.0, le=100.0)
    max_cloud_cover_pct: float = Field(80.0, ge=0.0, le=100.0)
    enabled: bool = True


class SchedulerConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    folder_path: str
    recursive: bool
    sensor_hint: str | None
    interval_minutes: int
    min_overlap_pct: float
    max_cloud_cover_pct: float
    enabled: bool
    last_scan_at: datetime | None
    updated_at: datetime


class SchedulerStatusResponse(BaseModel):
    enabled: bool
    last_scan_at: datetime | None
    configs: list[SchedulerConfigResponse]
