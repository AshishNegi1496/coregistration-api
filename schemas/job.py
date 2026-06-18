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


class CoregistrationParameters(BaseModel):
    """Custom coregistration parameters for manual processing."""
    grid_resolution: int = Field(2048, ge=512, le=8192, description="Grid resolution for tie point calculation")
    window_width: int = Field(256, ge=64, le=2048, description="Window size X dimension")
    window_height: int = Field(256, ge=64, le=2048, description="Window size Y dimension")
    maximum_shift_pixels: float = Field(100.0, ge=0, le=1000, description="Maximum allowed shift in pixels")
    tiepoint_filter_level: int = Field(3, ge=1, le=5, description="Tie point filter level (1-5)")
    minimum_reliability_percent: float = Field(40.0, ge=0, le=100, description="Minimum reliability percentage")
    ransac_maximum_outliers: int = Field(10, ge=1, le=100, description="Maximum outlier threshold")
    cpu_cores_used: int = Field(12, ge=1, le=64, description="Number of CPU cores to use")
    resampling_algorithm_calculation: Literal["nearest", "cubic", "bilinear"] = Field("nearest", description="Resampling algorithm for calculation")
    resampling_algorithm_deshift: Literal["nearest", "cubic", "bilinear"] = Field("nearest", description="Resampling algorithm for deshift")
    match_ground_sample_distance: bool = Field(True, description="Match GSD between reference and target")


class JobCreateRequest(BaseModel):
    target_path: str = Field(..., description="Absolute or root-relative path to the target image")
    base_path: str | None = Field(None, description="Optional absolute or root-relative path to the base image")
    sensor_type: str = Field("Sentinel-2", description="Sensor label stored with the job")
    priority: int = Field(5, ge=1, le=10)
    publish_to_geoserver: bool = Field(False)
    cloud_optimized_compression: str = Field("LZW")
    callback_url: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    use_custom_params: bool = Field(False, description="Enable custom coregistration parameters")
    custom_params: CoregistrationParameters | None = Field(None, description="Custom coregistration parameters (only used if use_custom_params=True)")


class BatchJobCreateRequest(BaseModel):
    items: list[JobCreateRequest]
    priority: int = Field(5, ge=1, le=10)


class AutoProcessRequest(BaseModel):
    target_paths: list[str]
    sensor_type: str | None = None
    priority: int = Field(5, ge=1, le=10)
    publish_to_geoserver: bool = Field(False)
    cloud_optimized_compression: str = Field("LZW")
    callback_url: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_number: int
    status: str
    processing_stage: str | None = None

    sensor_type: str

    reference_image_path: str
    target_image_path: str

    coregistered_output_path: str | None = None
    cloud_optimized_output_path: str | None = None

    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    processing_duration_seconds: float

    error_message: str | None = None


class JobDetailResponse(JobResponse):
    logs: list[JobLogResponse] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)


class BatchJobCreateResponse(BaseModel):
    batch_id: str | None
    job_numbers: list[int]
    created_count: int
    status: str
    created_at: datetime


class AutoProcessItemResult(BaseModel):
    target_path: str
    status: str
    job_number: int | None = None
    base_path: str | None = None
    sensor_type: str | None = None
    reason: str | None = None


class AutoProcessResponse(BaseModel):
    batch_id: UUID | None = None
    status: str
    created_count: int
    failed_count: int
    items: list[AutoProcessItemResult]
