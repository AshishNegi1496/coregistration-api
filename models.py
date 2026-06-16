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


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================
# COREG JOB
# ============================================================

class CoregJob(Base):
    __tablename__ = "coreg_job"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    job_no: Mapped[int] = mapped_column(
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

    stage: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="queued",
    )

    sensor_name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    reference_image: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    target_image: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    coreg_output_path: Mapped[str | None] = mapped_column(Text)
    cog_output_path: Mapped[str | None] = mapped_column(Text)

    runtime_seconds: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    error_message: Mapped[str | None] = mapped_column(Text)

    metrics: Mapped["CoregMetrics"] = relationship(
        back_populates="job",
        uselist=False,
        cascade="all, delete-orphan",
    )


# ============================================================
# HUB TABLE
# ============================================================

class CoregMetrics(Base):
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

    quality: Mapped[str | None] = mapped_column(String(32))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )

    job: Mapped["CoregJob"] = relationship(
        back_populates="metrics"
    )

    parameters: Mapped["CoregParameter"] = relationship(
        back_populates="metrics",
        uselist=False,
        cascade="all, delete-orphan",
    )

    pixel_size: Mapped["CoregPixelSize"] = relationship(
        back_populates="metrics",
        uselist=False,
        cascade="all, delete-orphan",
    )

    system_performance: Mapped["CoregSystemPerformance"] = relationship(
        back_populates="metrics",
        uselist=False,
        cascade="all, delete-orphan",
    )

    overall_stat: Mapped["CoregOverallStat"] = relationship(
        back_populates="metrics",
        uselist=False,
        cascade="all, delete-orphan",
    )


# ============================================================
# PARAMETERS
# ============================================================

class CoregParameter(Base):
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

    im_ref: Mapped[str] = mapped_column(Text)
    im_tgt: Mapped[str] = mapped_column(Text)

    grid_res: Mapped[int] = mapped_column(Integer)

    window_x: Mapped[int] = mapped_column(Integer)
    window_y: Mapped[int] = mapped_column(Integer)

    max_shift: Mapped[float] = mapped_column(Float)

    tieP_filter_level: Mapped[int] = mapped_column(Integer)

    min_reliability: Mapped[float] = mapped_column(Float)

    rs_max_outlier: Mapped[int] = mapped_column(Integer)

    CPUs: Mapped[int] = mapped_column(Integer)

    fmt_out: Mapped[str] = mapped_column(String(32))

    path_out: Mapped[str] = mapped_column(Text)

    resamp_alg_calc: Mapped[str] = mapped_column(String(32))

    resamp_alg_deshift: Mapped[str] = mapped_column(String(32))

    match_gsd: Mapped[bool] = mapped_column(Boolean)

    q: Mapped[bool] = mapped_column(Boolean)

    metrics: Mapped["CoregMetrics"] = relationship(
        back_populates="parameters"
    )


# ============================================================
# PIXEL SIZE
# ============================================================

class CoregPixelSize(Base):
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

    target_x: Mapped[float] = mapped_column(Float)
    target_y: Mapped[float] = mapped_column(Float)

    output_x: Mapped[float] = mapped_column(Float)
    output_y: Mapped[float] = mapped_column(Float)

    metrics: Mapped["CoregMetrics"] = relationship(
        back_populates="pixel_size"
    )


# ============================================================
# SYSTEM PERFORMANCE
# ============================================================

class CoregSystemPerformance(Base):
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

    cpu_percent: Mapped[float] = mapped_column(Float)
    cores: Mapped[int] = mapped_column(Integer)

    ram_total_gb: Mapped[float] = mapped_column(Float)
    ram_available_gb: Mapped[float] = mapped_column(Float)
    ram_used_gb: Mapped[float] = mapped_column(Float)
    ram_percent: Mapped[float] = mapped_column(Float)

    process_ram_gb: Mapped[float] = mapped_column(Float)

    disk_read_mb: Mapped[float] = mapped_column(Float)
    disk_write_mb: Mapped[float] = mapped_column(Float)

    process_threads: Mapped[int] = mapped_column(Integer)

    metrics: Mapped["CoregMetrics"] = relationship(
        back_populates="system_performance"
    )


# ============================================================
# OVERALL STATS
# ============================================================

class CoregOverallStat(Base):
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

    N_TP: Mapped[int] = mapped_column(Integer)

    valid_tiepoints: Mapped[int] = mapped_column(Integer)
    invalid_tiepoints: Mapped[int] = mapped_column(Integer)

    valid_percent: Mapped[float] = mapped_column(Float)
    invalid_percent: Mapped[float] = mapped_column(Float)

    RMSE_X: Mapped[float] = mapped_column(Float)
    RMSE_Y: Mapped[float] = mapped_column(Float)
    RMSE_M: Mapped[float] = mapped_column(Float)
    RMSE_PX: Mapped[float] = mapped_column(Float)

    MSE_X: Mapped[float] = mapped_column(Float)
    MSE_Y: Mapped[float] = mapped_column(Float)

    MAE_X: Mapped[float] = mapped_column(Float)
    MAE_Y: Mapped[float] = mapped_column(Float)

    SHIFT_MEAN: Mapped[float] = mapped_column(Float)
    SHIFT_MEDIAN: Mapped[float] = mapped_column(Float)
    SHIFT_STD: Mapped[float] = mapped_column(Float)
    SHIFT_MIN: Mapped[float] = mapped_column(Float)
    SHIFT_MAX: Mapped[float] = mapped_column(Float)

    ANGLE_MEAN: Mapped[float] = mapped_column(Float)

    SSIM_MEAN: Mapped[float] = mapped_column(Float)

    RELIABILITY_MEAN: Mapped[float] = mapped_column(Float)
    RELIABILITY_MEDIAN: Mapped[float] = mapped_column(Float)

    metrics: Mapped["CoregMetrics"] = relationship(
        back_populates="overall_stat"
    )