from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict


class JobLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    step_name: str
    level: str
    message: str
    timestamp: datetime


class CoregParameters(BaseModel):
    """Custom coregistration parameters for manual processing."""
    grid_res: int = Field(2048, ge=512, le=8192, description="Grid resolution for tie point calculation")
    window_size_x: int = Field(256, ge=64, le=2048, description="Window size X dimension")
    window_size_y: int = Field(256, ge=64, le=2048, description="Window size Y dimension")
    max_shift: float = Field(100.0, ge=0, le=1000, description="Maximum allowed shift in pixels")
    tieP_filter_level: int = Field(3, ge=1, le=5, description="Tie point filter level (1-5)")
    min_reliability: float = Field(40.0, ge=0, le=100, description="Minimum reliability percentage")
    rs_max_outlier: int = Field(10, ge=1, le=100, description="Maximum outlier threshold")
    CPUs: int = Field(12, ge=1, le=64, description="Number of CPU cores to use")
    resamp_alg_calc: Literal["nearest", "cubic", "bilinear"] = Field("nearest", description="Resampling algorithm for calculation")
    resamp_alg_deshift: Literal["nearest", "cubic", "bilinear"] = Field("nearest", description="Resampling algorithm for deshift")
    match_gsd: bool = Field(True, description="Match GSD between reference and target")


class JobCreateRequest(BaseModel):
    target_path: str = Field(..., description="Absolute or root-relative path to the target image")
    base_path: str | None = Field(None, description="Optional absolute or root-relative path to the base image")
    sensor_name: str = Field("Sentinel-2", description="Sensor label stored with the job")
    priority: int = Field(5, ge=1, le=10)
    publish_to_geoserver: bool = Field(False)
    cog_compression: str = Field("LZW")
    callback_url: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    use_custom_params: bool = Field(False, description="Enable custom coregistration parameters")
    custom_params: CoregParameters | None = Field(None, description="Custom coregistration parameters (only used if use_custom_params=True)")


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
