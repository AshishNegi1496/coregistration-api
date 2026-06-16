from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PlatformMetricsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_jobs: int
    queued_jobs: int
    running_jobs: int
    completed_jobs: int
    failed_jobs: int
    cancelled_jobs: int
    average_priority: float
    average_runtime_seconds: float
    sensor_distribution: dict[str, int]
