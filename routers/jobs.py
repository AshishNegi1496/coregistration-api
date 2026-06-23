from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from db import get_db
from models import CoregistrationJob
from schemas.job import (
    AutoProcessItemResult,
    AutoProcessRequest,
    AutoProcessResponse,
    JobCreateRequest,
    JobDetailResponse,
    JobResponse,
)
from services.job_service import (
    create_job,
    job_to_detail,
    job_to_response,
    load_existing_target_paths,
    match_base_for_target,
    process_job,
    resolve_sensor_type,
)
from utils import normalize_path, resolve_input_path

router = APIRouter(prefix="/jobs", tags=["Jobs"])
log = logging.getLogger("api.jobs")


@router.post("/auto-process", response_model=AutoProcessResponse, status_code=status.HTTP_201_CREATED)
async def auto_process_targets(request: AutoProcessRequest, db: Session = Depends(get_db)):
    if not request.target_paths:
        raise HTTPException(status_code=400, detail="Select at least one target file.")

    results: list[AutoProcessItemResult] = []
    existing_targets = load_existing_target_paths(db, active_only=True)

    for raw_target in request.target_paths:
        try:
            target_path = resolve_input_path(settings.target_root, raw_target)
        except ValueError as exc:
            results.append(AutoProcessItemResult(target_path=raw_target, status="failed", reason=str(exc)))
            continue

        if not target_path.exists():
            results.append(AutoProcessItemResult(
                target_path=str(target_path), status="failed",
                reason=f"Target file not found: {target_path}",
            ))
            continue

        if normalize_path(target_path) in existing_targets:
            results.append(AutoProcessItemResult(
                target_path=str(target_path), status="failed",
                reason="Target image has already been processed.",
            ))
            continue

        base_path, match_reason = match_base_for_target(target_path, request.sensor_type)
        if base_path is None:
            results.append(AutoProcessItemResult(target_path=str(target_path), status="failed", reason=match_reason))
            continue

        job = create_job(db, target_path, base_path, resolve_sensor_type(target_path, request.sensor_type))
        db.commit()
        process_job(job, target_path, base_path, db)
        db.refresh(job)
        existing_targets.add(normalize_path(target_path))

        results.append(AutoProcessItemResult(
            target_path=str(target_path),
            status=job.status,
            job_number=job.job_number,
            base_path=job.reference_image_path,
            sensor_type=job.sensor_type,
            reason=match_reason,
        ))

    created_count = sum(1 for item in results if item.status == "completed")
    failed_count = sum(1 for item in results if item.status == "failed")
    overall_status = "completed" if created_count and not failed_count else "partial" if created_count else "failed"

    return AutoProcessResponse(
        status=overall_status,
        created_count=created_count,
        failed_count=failed_count,
        items=results,
    )


@router.post("/process", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def submit_job(request: JobCreateRequest, db: Session = Depends(get_db)):
    if request.use_custom_params and not request.custom_params:
        raise HTTPException(status_code=400, detail="Custom parameters enabled but no custom_params provided.")

    target_path = resolve_input_path(settings.target_root, request.target_path)
    if not target_path.exists():
        raise HTTPException(status_code=400, detail=f"Target file not found: {target_path}")

    base_path = (
        resolve_input_path(settings.base_root, request.base_path)
        if request.base_path
        else match_base_for_target(target_path, request.sensor_type)[0]
    )
    if base_path is None:
        raise HTTPException(status_code=400, detail="No matching base image found.")

    job = create_job(db, target_path, base_path, resolve_sensor_type(target_path, request.sensor_type))
    db.commit()

    custom_params = request.custom_params.model_dump() if request.use_custom_params and request.custom_params else None
    process_job(job, target_path, base_path, db, custom_params)
    db.refresh(job)
    return job_to_response(job)


@router.get("", response_model=list[JobResponse])
async def list_jobs(
    status: str | None = Query(None),
    sensor_type: str | None = Query(None),
    search: str | None = Query(None),
    db: Session = Depends(get_db),
):
    jobs = list(db.scalars(select(CoregistrationJob).order_by(CoregistrationJob.job_number.desc())))
    if status:
        jobs = [job for job in jobs if job.status == status]
    if sensor_type:
        jobs = [job for job in jobs if job.sensor_type == sensor_type]
    if search:
        query = search.lower()
        jobs = [job for job in jobs if query in job.target_image_path.lower() or query in str(job.job_number)]
    return [job_to_response(job) for job in jobs]


@router.patch("/{job_number}/cancel", response_model=JobDetailResponse)
async def cancel_job(job_number: int, db: Session = Depends(get_db)):
    job = db.scalar(select(CoregistrationJob).where(CoregistrationJob.job_number == job_number))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status in {"completed", "cancelled"}:
        raise HTTPException(status_code=400, detail="Job is already finished.")

    job.status = "cancelled"
    job.processing_stage = "cancelled"
    job.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    return job_to_detail(job)
