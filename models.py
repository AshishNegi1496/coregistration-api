from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Sequence,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db import Base


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


# ============================================================
# COREGISTRATION JOB
# ============================================================

class CoregistrationJob(Base):
    """Represents a coregistration processing job."""
    __tablename__ = "coreg_job"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    job_number: Mapped[int] = mapped_column(
        Integer,
        Sequence("coreg_job_no_seq", start=1000),
        unique=True,
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="queued",
        index=True,
    )

    processing_stage: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="queued",
    )

    sensor_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    reference_image_path: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    target_image_path: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    coregistered_output_path: Mapped[str | None] = mapped_column(Text)
    cloud_optimized_output_path: Mapped[str | None] = mapped_column(Text)

    processing_duration_seconds: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    error_message: Mapped[str | None] = mapped_column(Text)

    metrics: Mapped["CoregistrationMetrics"] = relationship(
        back_populates="job",
        uselist=False,
        cascade="all, delete-orphan",
    )


# ============================================================
# HUB TABLE - COREGISTRATION METRICS
# ============================================================

class CoregistrationMetrics(Base):
    """Stores quality metrics and results for a coregistration job."""
    __tablename__ = "coreg_metrics"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("coreg_job.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    quality_rating: Mapped[str | None] = mapped_column(String(32))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )

    job: Mapped["CoregistrationJob"] = relationship(
        back_populates="metrics"
    )

    parameters: Mapped["CoregistrationParameters"] = relationship(
        back_populates="metrics_record",
        uselist=False,
        cascade="all, delete-orphan",
    )

    pixel_size_info: Mapped["CoregistrationPixelSize"] = relationship(
        back_populates="metrics_record",
        uselist=False,
        cascade="all, delete-orphan",
    )

    system_performance: Mapped["SystemPerformanceMetrics"] = relationship(
        back_populates="metrics_record",
        uselist=False,
        cascade="all, delete-orphan",
    )

    overall_statistics: Mapped["OverallStatistics"] = relationship(
        back_populates="metrics_record",
        uselist=False,
        cascade="all, delete-orphan",
    )


# ============================================================
# COREGISTRATION PARAMETERS
# ============================================================

class CoregistrationParameters(Base):
    """Stores processing parameters used for coregistration."""
    __tablename__ = "coreg_parameter"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    metrics_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("coreg_metrics.id", ondelete="CASCADE"),
        unique=True,
    )

    reference_image_path: Mapped[str] = mapped_column(Text)
    target_image_path: Mapped[str] = mapped_column(Text)

    grid_resolution: Mapped[int] = mapped_column(Integer)

    window_width: Mapped[int] = mapped_column(Integer)
    window_height: Mapped[int] = mapped_column(Integer)

    maximum_shift_pixels: Mapped[float] = mapped_column(Float)

    tiepoint_filter_level: Mapped[int] = mapped_column(Integer)

    minimum_reliability_percent: Mapped[float] = mapped_column(Float)

    ransac_maximum_outliers: Mapped[int] = mapped_column(Integer)

    cpu_cores_used: Mapped[int] = mapped_column(Integer)

    output_format: Mapped[str] = mapped_column(String(32))

    output_directory: Mapped[str] = mapped_column(Text)

    resampling_algorithm_calculation: Mapped[str] = mapped_column(String(32))

    resampling_algorithm_deshift: Mapped[str] = mapped_column(String(32))

    match_ground_sample_distance: Mapped[bool] = mapped_column(Boolean)

    quiet_mode: Mapped[bool] = mapped_column(Boolean)

    metrics_record: Mapped["CoregistrationMetrics"] = relationship(
        back_populates="parameters"
    )


# ============================================================
# PIXEL SIZE INFORMATION
# ============================================================

class CoregistrationPixelSize(Base):
    """Stores pixel size (ground sample distance) information."""
    __tablename__ = "coreg_pixel_size"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    metrics_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("coreg_metrics.id", ondelete="CASCADE"),
        unique=True,
    )

    target_pixel_size_x: Mapped[float] = mapped_column(Float)
    target_pixel_size_y: Mapped[float] = mapped_column(Float)

    output_pixel_size_x: Mapped[float] = mapped_column(Float)
    output_pixel_size_y: Mapped[float] = mapped_column(Float)

    metrics_record: Mapped["CoregistrationMetrics"] = relationship(
        back_populates="pixel_size_info"
    )


# ============================================================
# SYSTEM PERFORMANCE METRICS
# ============================================================

class SystemPerformanceMetrics(Base):
    """Stores system resource usage during processing."""
    __tablename__ = "coreg_system_performance"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    metrics_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("coreg_metrics.id", ondelete="CASCADE"),
        unique=True,
    )

    cpu_usage_percent: Mapped[float] = mapped_column(Float)
    cpu_cores_count: Mapped[int] = mapped_column(Integer)

    ram_total_gb: Mapped[float] = mapped_column(Float)
    ram_available_gb: Mapped[float] = mapped_column(Float)
    ram_used_gb: Mapped[float] = mapped_column(Float)
    ram_usage_percent: Mapped[float] = mapped_column(Float)

    process_memory_gb: Mapped[float] = mapped_column(Float)

    disk_read_mb: Mapped[float] = mapped_column(Float)
    disk_write_mb: Mapped[float] = mapped_column(Float)

    process_thread_count: Mapped[int] = mapped_column(Integer)

    metrics_record: Mapped["CoregistrationMetrics"] = relationship(
        back_populates="system_performance"
    )


# ============================================================
# OVERALL STATISTICS
# ============================================================

class OverallStatistics(Base):
    """Stores statistical results from coregistration analysis."""
    __tablename__ = "coreg_overall_stat"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    metrics_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("coreg_metrics.id", ondelete="CASCADE"),
        unique=True,
    )

    total_tiepoints: Mapped[int] = mapped_column(Integer)

    valid_tiepoints: Mapped[int] = mapped_column(Integer)
    invalid_tiepoints: Mapped[int] = mapped_column(Integer)

    valid_percent: Mapped[float] = mapped_column(Float)
    invalid_percent: Mapped[float] = mapped_column(Float)

    rmse_x: Mapped[float] = mapped_column(Float)
    rmse_y: Mapped[float] = mapped_column(Float)
    rmse_magnitude: Mapped[float] = mapped_column(Float)
    rmse_pixels: Mapped[float] = mapped_column(Float)

    mse_x: Mapped[float] = mapped_column(Float)
    mse_y: Mapped[float] = mapped_column(Float)

    mae_x: Mapped[float] = mapped_column(Float)
    mae_y: Mapped[float] = mapped_column(Float)

    shift_mean: Mapped[float] = mapped_column(Float)
    shift_median: Mapped[float] = mapped_column(Float)
    shift_std: Mapped[float] = mapped_column(Float)
    shift_min: Mapped[float] = mapped_column(Float)
    shift_max: Mapped[float] = mapped_column(Float)

    angle_mean: Mapped[float] = mapped_column(Float)

    ssim_mean: Mapped[float] = mapped_column(Float)

    reliability_mean: Mapped[float] = mapped_column(Float)
    reliability_median: Mapped[float] = mapped_column(Float)

    metrics_record: Mapped["CoregistrationMetrics"] = relationship(
        back_populates="overall_statistics"
    )


# ============================================================
# SCHEDULER CONFIGURATION
# ============================================================

class SchedulerConfiguration(Base):
    """Stores scheduler configuration for automatic processing."""
    __tablename__ = "scheduler_config"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    folder_path: Mapped[str] = mapped_column(Text, nullable=False)
    recursive_scan: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sensor_hint: Mapped[str | None] = mapped_column(String(64))
    
    scan_interval_minutes: Mapped[int] = mapped_column(
        Integer,
        default=60,
        nullable=False,
    )
    
    minimum_overlap_percent: Mapped[float] = mapped_column(Float, default=10.0)
    maximum_cloud_cover_percent: Mapped[float] = mapped_column(Float, default=80.0)
    
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )