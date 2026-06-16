from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db import get_db
from api.models import CoregJob, CoregMetrics, CoregParameter, CoregPixelSize, CoregSystemPerformance, CoregOverallStat
from api.schemas.metrics import PlatformMetricsResponse

router = APIRouter(prefix="/metrics", tags=["Metrics"])


@router.get("", response_model=PlatformMetricsResponse)
async def get_platform_metrics(db: Session = Depends(get_db)):
    jobs = list(db.scalars(select(Job)))
    status_counts = Counter(job.status for job in jobs)
    sensor_counts = Counter(job.sensor_name for job in jobs)

    total_jobs = len(jobs)
    average_priority = sum(job.priority for job in jobs) / total_jobs if total_jobs else 0.0
    average_runtime = sum(job.runtime_seconds for job in jobs) / total_jobs if total_jobs else 0.0

    return PlatformMetricsResponse(
        total_jobs=total_jobs,
        queued_jobs=status_counts.get("queued", 0),
        running_jobs=status_counts.get("running", 0),
        completed_jobs=status_counts.get("completed", 0),
        failed_jobs=status_counts.get("failed", 0),
        cancelled_jobs=status_counts.get("cancelled", 0),
        average_priority=round(average_priority, 2),
        average_runtime_seconds=round(average_runtime, 2),
        sensor_distribution=dict(sensor_counts),
    )
