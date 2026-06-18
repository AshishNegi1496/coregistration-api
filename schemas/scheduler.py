from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class PeriodicityRequest(BaseModel):
    """Request to set the scan periodicity in minutes."""
    interval_minutes: int = Field(60, ge=1, description="Interval in minutes (e.g., 1, 5, 60, 120)")


class AutoscanResponse(BaseModel):
    """Response from the autoscan endpoint."""
    status: str
    scanned_folders: list[str]
    new_files_found: list[str]
    jobs_started: list[int]
    message: str | None = None


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
