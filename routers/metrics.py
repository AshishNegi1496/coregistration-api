from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from db import get_db
from models import CoregistrationJob
from schemas.metrics import PlatformMetricsResponse

router = APIRouter(prefix="/metrics", tags=["Metrics"])


@router.get("", response_model=PlatformMetricsResponse)
async def get_platform_metrics(db: Session = Depends(get_db)):
    jobs = list(db.scalars(select(CoregistrationJob)))
    status_counts = Counter(job.status for job in jobs)
    sensor_counts = Counter(job.sensor_type for job in jobs)

    total_jobs = len(jobs)
    average_runtime = (
        sum(job.processing_duration_seconds or 0.0 for job in jobs) / total_jobs
        if total_jobs
        else 0.0
    )

    return PlatformMetricsResponse(
        total_jobs=total_jobs,
        queued_jobs=status_counts.get("queued", 0),
        running_jobs=status_counts.get("running", 0),
        completed_jobs=status_counts.get("completed", 0),
        failed_jobs=status_counts.get("failed", 0),
        cancelled_jobs=status_counts.get("cancelled", 0),
        average_priority=0.0,
        average_runtime_seconds=round(average_runtime, 2),
        sensor_distribution=dict(sensor_counts),
    )
