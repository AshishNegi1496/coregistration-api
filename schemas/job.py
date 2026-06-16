from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict


class JobLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    step_name: str
    level: str
    message: str
    timestamp: datetime


class JobCreateRequest(BaseModel):
    target_path: str = Field(..., description="Absolute or root-relative path to the target image")
    base_path: str | None = Field(None, description="Optional absolute or root-relative path to the base image")
    sensor_name: str = Field("Sentinel-2", description="Sensor label stored with the job")
    priority: int = Field(5, ge=1, le=10)
    publish_to_geoserver: bool = Field(False)
    cog_compression: str = Field("LZW")
    callback_url: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class BatchJobCreateRequest(BaseModel):
    items: list[JobCreateRequest]
    priority: int = Field(5, ge=1, le=10)


class AutoProcessRequest(BaseModel):
    target_paths: list[str]
    sensor_name: str | None = None
    priority: int = Field(5, ge=1, le=10)
    publish_to_geoserver: bool = Field(False)
    cog_compression: str = Field("LZW")
    callback_url: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_no: int
    status: str
    stage: str | None = None

    sensor_name: str

    reference_image: str
    target_image: str

    coreg_output_path: str | None = None
    cog_output_path: str | None = None

    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    runtime_seconds: float

    error_message: str | None = None


class JobDetailResponse(JobResponse):
    logs: list[JobLogResponse] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)


class BatchJobCreateResponse(BaseModel):
    batch_id: str | None
    job_nos: list[int]
    created_count: int
    status: str
    created_at: datetime


class AutoProcessItemResult(BaseModel):
    target_path: str
    status: str
    job_no: int | None = None
    base_path: str | None = None
    sensor_name: str | None = None
    reason: str | None = None


class AutoProcessResponse(BaseModel):
    batch_id: UUID | None = None
    status: str
    created_count: int
    failed_count: int
    items: list[AutoProcessItemResult]
