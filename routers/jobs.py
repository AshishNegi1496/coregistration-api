from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.config import settings
from api.coreg_service import run_coregistration_and_cog
from api.db import get_db
from api.models import CoregJob, CoregMetrics, CoregOverallStat, CoregParameter, CoregPixelSize, CoregSystemPerformance
from api.schemas.job import (
    AutoProcessItemResult,
    AutoProcessRequest,
    AutoProcessResponse,
    CoregParameters,
    JobCreateRequest,
    JobDetailResponse,
    JobResponse,
)
from api.utils import (
    ensure_dir,
    gdal_pixel_size,
    geo_overlap_metrics,
    infer_sensor_label,
    list_image_files,
    resolve_input_path,
    shared_token_count,
)
from pathlib import Path


def normalize_path(path: str) -> str:
    return str(Path(path).resolve()).replace("\\", "/").lower()


router = APIRouter(prefix="/jobs", tags=["Jobs"])
log = logging.getLogger("api.jobs")


def _match_base_for_target(target_path: Path, preferred_sensor: str | None = None) -> tuple[Path | None, str]:
    base_files = list_image_files(settings.base_root, recursive=True)
    if not base_files:
        log.warning("No base files found under %s", settings.base_root)
        return None, "No base image found in BASE_ROOT."

    sensor_hint = infer_sensor_label(preferred_sensor) if preferred_sensor else None
    scored_candidates: list[dict[str, object]] = []
    log.info("Matching target=%s sensor_hint=%s against %d base files", target_path, sensor_hint or "none", len(base_files))

    for candidate in base_files:
        metrics = geo_overlap_metrics(target_path, candidate)
        candidate_sensor = infer_sensor_label(f"{candidate.name} {candidate.parent}")
        sensor_score = 1 if sensor_hint and candidate_sensor == sensor_hint else 0
        gsd = gdal_pixel_size(candidate)
        geo_available = metrics is not None
        geo_overlap = float(metrics["intersection_area"]) if metrics else 0.0
        bbox_overlap = float(metrics["bbox_overlap_pct"]) if metrics else 0.0
        extent_overlap = float(metrics["extent_intersection_pct"]) if metrics else 0.0
        geometry_overlap = float(metrics["geometry_overlap_pct"]) if metrics else 0.0
        latlon_overlap = float(metrics["latlon_overlap_pct"]) if metrics else 0.0
        token_score = shared_token_count(target_path, candidate)
        has_geo_match = geo_available and geo_overlap > 0

        log.info(
            "Candidate=%s geo_available=%s geo_overlap=%.3f crs_match=%s bbox_overlap=%.3f extent_intersection=%.3f geometry_overlap=%.3f latlon_overlap=%.3f sensor=%s token_score=%s gsd=%s",
            candidate, geo_available, geo_overlap, metrics["same_crs"] if metrics else False,
            bbox_overlap, extent_overlap, geometry_overlap, latlon_overlap,
            candidate_sensor or "unknown", token_score, gsd if gsd else "unknown",
        )
        scored_candidates.append({
            "path": candidate,
            "has_geo_match": 1 if has_geo_match else 0,
            "same_crs": 1 if (metrics and metrics["same_crs"]) else 0,
            "geometry_overlap_pct": geometry_overlap,
            "bbox_overlap_pct": bbox_overlap,
            "latlon_overlap_pct": latlon_overlap,
            "extent_intersection_pct": extent_overlap,
            "sensor_score": sensor_score,
            "token_score": token_score,
            "gsd": gsd if gsd else float("inf"),
            "metrics": metrics,
        })

    if not scored_candidates:
        log.warning("No overlapping base candidate found for target=%s", target_path)
        return None, f"No geospatial overlap found for target '{target_path.name}' in BASE_ROOT."

    geo_candidates = [item for item in scored_candidates if item["has_geo_match"]]
    candidate_pool = geo_candidates if geo_candidates else scored_candidates
    if not geo_candidates:
        log.warning("No geospatial overlap detected for target=%s; falling back to filename/sensor token matching.", target_path)

    candidate_pool.sort(
        key=lambda item: (
            item["has_geo_match"], item["same_crs"], item["geometry_overlap_pct"],
            item["bbox_overlap_pct"], item["latlon_overlap_pct"], item["extent_intersection_pct"],
            item["sensor_score"], item["token_score"], -float(item["gsd"]), str(item["path"]).lower(),
        ),
        reverse=True,
    )
    chosen = candidate_pool[0]["path"]
    metrics = candidate_pool[0]["metrics"]

    if metrics and candidate_pool[0]["has_geo_match"]:
        crs_text = "CRS match" if metrics["same_crs"] else "CRS transformed"
        reason = f"matched by {crs_text}, bbox overlap {metrics['bbox_overlap_pct']}%, extent intersection {metrics['extent_intersection_pct']}%, geometry overlap {metrics['geometry_overlap_pct']}%, lat/lon overlap {metrics['latlon_overlap_pct']}%."
    else:
        reason = f"used fallback token/sensor match for target '{target_path.stem}' against base '{chosen.stem}'."

    log.info("Selected base=%s for target=%s reason=%s", chosen, target_path, reason)
    return chosen, reason


def _new_job_no_path(job_no: int, target_path: Path) -> tuple[Path, Path, Path]:
    run_root = ensure_dir(settings.output_root / f"job_{job_no:04d}")
    coreg_dir = ensure_dir(run_root / "coreg")
    cog_dir = ensure_dir(run_root / "cog")
    coreg_output = coreg_dir / f"{target_path.stem}_coregistered.tif"
    cog_output = cog_dir / f"{target_path.stem}_cog.tif"
    return run_root, coreg_output, cog_output


def _get_sensor_name(target_path: Path, provided_name: str | None) -> str:
    return provided_name or infer_sensor_label(str(target_path)) or "unknown"


def _create_job(db: Session, target_path: Path, base_path: Path, sensor_name: str) -> CoregJob:
    job = CoregJob(
        status="queued", stage="queued", sensor_name=sensor_name,
        reference_image=str(base_path), target_image=str(target_path),
        runtime_seconds=0.0, created_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.flush()

    _, coreg_output, cog_output = _new_job_no_path(job.job_no, target_path)
    log.info("Allocated job_no=%s run_root=%s coreg_output=%s cog_output=%s", job.job_no, coreg_output.parent.parent, coreg_output, cog_output)
    job.coreg_output_path = str(coreg_output)
    job.cog_output_path = str(cog_output)
    db.flush()
    return job


def _job_to_response(job: CoregJob) -> JobResponse:
    return JobResponse.model_validate({
        "job_no": job.job_no or 0, "status": job.status, "stage": job.stage,
        "sensor_name": job.sensor_name, "reference_image": job.reference_image,
        "target_image": job.target_image, "coreg_output_path": job.coreg_output_path,
        "cog_output_path": job.cog_output_path, "created_at": job.created_at,
        "started_at": job.started_at, "completed_at": job.completed_at,
        "runtime_seconds": job.runtime_seconds, "error_message": job.error_message,
    })


def _job_to_detail(job: CoregJob) -> JobDetailResponse:
    payload = _job_to_response(job).model_dump()
    if job.metrics:
        payload["quality"] = job.metrics.quality
    return JobDetailResponse.model_validate(payload)

def _create_metrics_for_job(db: Session, job: CoregJob, result: dict) -> None:
    """Create and persist CoregMetrics and all related child records after successful coregistration."""
    import psutil
    
    existing = db.scalar(
    select(CoregMetrics).where(
        CoregMetrics.job_id == job.id
    )
    )

    if existing:
        return

    metrics = CoregMetrics(
        job_id=job.id,
        quality=result.get("quality"),
    )
    db.add(metrics)
    db.flush()

    params = result.get("parameters", {})
    parameter = CoregParameter(
        metrics_id=metrics.id,
        im_ref=job.reference_image,
        im_tgt=job.target_image,
        grid_res=params.get("grid_res", 0),
        window_x=params.get("window_size", (0, 0))[0] if isinstance(params.get("window_size"), tuple) else 0,
        window_y=params.get("window_size", (0, 0))[1] if isinstance(params.get("window_size"), tuple) else 0,
        max_shift=params.get("max_shift", 0.0),
        tieP_filter_level=params.get("tieP_filter_level", 3),
        min_reliability=params.get("min_reliability", 40.0),
        rs_max_outlier=params.get("rs_max_outlier", 10),
        CPUs=params.get("CPUs", 12),
        fmt_out=params.get("fmt_out", "GTiff"),
        path_out=params.get("path_out", str(job.coreg_output_path)),
        resamp_alg_calc=params.get("resamp_alg_calc", "nearest"),
        resamp_alg_deshift=params.get("resamp_alg_deshift", "nearest"),
        match_gsd=params.get("match_gsd", True),
        q=params.get("q", False),
    )
    db.add(parameter)

    try:
        from osgeo import gdal
        tgt_ds = gdal.Open(job.target_image)
        out_ds = gdal.Open(job.coreg_output_path) if job.coreg_output_path else None

        target_gt = tgt_ds.GetGeoTransform() if tgt_ds else (0, 0, 0, 0, 0, 0)
        output_gt = out_ds.GetGeoTransform() if out_ds else (0, 0, 0, 0, 0, 0)

        pixel_size = CoregPixelSize(
            metrics_id=metrics.id,
            target_x=abs(target_gt[1]) if target_gt else 0.0,
            target_y=abs(target_gt[5]) if target_gt else 0.0,
            output_x=abs(output_gt[1]) if output_gt else 0.0,
            output_y=abs(output_gt[5]) if output_gt else 0.0,
        )
        db.add(pixel_size)
    except Exception:
        pass

    process = psutil.Process()
    cpu_percent = psutil.cpu_percent(interval=0.1)
    mem_info = process.memory_info()
    vmem = psutil.virtual_memory()

    system_perf = CoregSystemPerformance(
        metrics_id=metrics.id,
        cpu_percent=cpu_percent,
        cores=psutil.cpu_count(logical=False) or 1,
        ram_total_gb=vmem.total / (1024**3),
        ram_available_gb=vmem.available / (1024**3),
        ram_used_gb=vmem.used / (1024**3),
        ram_percent=vmem.percent,
        process_ram_gb=mem_info.rss / (1024**3),
        disk_read_mb=getattr(process.io_counters(), 'read_bytes', 0) / (1024**2) if hasattr(process, 'io_counters') else 0.0,
        disk_write_mb=getattr(process.io_counters(), 'write_bytes', 0) / (1024**2) if hasattr(process, 'io_counters') else 0.0,
        process_threads=process.num_threads(),
    )
    db.add(system_perf)

    overall_stat = CoregOverallStat(
        metrics_id=metrics.id,
        N_TP=result.get("matched_points", 0),
        valid_tiepoints=result.get("valid_points", 0),
        invalid_tiepoints=max(0, result.get("matched_points", 0) - result.get("valid_points", 0)),
        valid_percent=(result.get("valid_points", 0) / result.get("matched_points", 1)) * 100 if result.get("matched_points", 0) > 0 else 0.0,
        invalid_percent=100.0 - ((result.get("valid_points", 0) / result.get("matched_points", 1)) * 100 if result.get("matched_points", 0) > 0 else 0.0),
        RMSE_X=0.0,
        RMSE_Y=0.0,
        RMSE_M=0.0,
        RMSE_PX=0.0,
        MSE_X=0.0,
        MSE_Y=0.0,
        MAE_X=0.0,
        MAE_Y=0.0,
        SHIFT_MEAN=0.0,
        SHIFT_MEDIAN=0.0,
        SHIFT_STD=0.0,
        SHIFT_MIN=0.0,
        SHIFT_MAX=0.0,
        ANGLE_MEAN=0.0,
        SSIM_MEAN=0.0,
        RELIABILITY_MEAN=0.0,
        RELIABILITY_MEDIAN=0.0,
    )
    db.add(overall_stat)

    job.metrics = metrics
    db.flush()

def _process_job(job: CoregJob, target_path: Path, base_path: Path, db: Session, custom_params: dict | None = None) -> None:
    """Process a coregistration job with optional custom parameters."""
    run_root = Path(job.coreg_output_path).parent.parent if job.coreg_output_path else ensure_dir(settings.output_root / f"job_{job.job_no:04d}")
    start = datetime.now(timezone.utc)
    log.info(
        "Starting processing job_no=%s target=%s base=%s run_root=%s custom_params=%s",
        job.job_no, target_path, base_path, run_root, "yes" if custom_params else "no",
    )

    job.status = "running"
    job.stage = "coregistration"
    job.started_at = start
  
    db.commit()

    try:
        result = run_coregistration_and_cog(base_path, target_path, run_root, custom_params)
        
        log.info(
            "Coregistration finished job_no=%s coreg_output=%s cog_output=%s",
            job.job_no, result.get("coreg_output"), result.get("cog_output"),
        )
        job.coreg_output_path = result["coreg_output"]
        job.cog_output_path = result["cog_output"]

        job.status = "completed"
        job.stage = "completed"
        job.completed_at = datetime.now(timezone.utc)

        _create_metrics_for_job(db, job, result)

        job.runtime_seconds = round((job.completed_at - start).total_seconds(), 2)

        db.commit()
        log.info("Job completed job_no=%s runtime_seconds=%s", job.job_no, job.runtime_seconds)
    except Exception as exc:
        db.rollback()
        log.exception("Job failed job_no=%s target=%s base=%s", job.job_no, target_path, base_path)
        job.status = "failed"
        job.stage = "failed"
        job.error_message = str(exc)
        job.completed_at = datetime.now(timezone.utc)
        job.runtime_seconds = round((job.completed_at - start).total_seconds(), 2)
        db.commit()


@router.post("/auto-process", response_model=AutoProcessResponse, status_code=status.HTTP_201_CREATED)
async def auto_process_targets(request: AutoProcessRequest, db: Session = Depends(get_db)):
    if not request.target_paths:
        raise HTTPException(status_code=400, detail="Select at least one target file.")

    # batch_id = uuid.uuid4() if len(request.target_paths) > 1 else None
    results: list[AutoProcessItemResult] = []
    log.info(
        "Auto process requested target_count=%d batch_id=%s sensor_name=%s priority=%s",
        len(request.target_paths),
        # batch_id,
        request.sensor_name or "none",
        request.priority,
    )
    
    existing_targets = {
    normalize_path(path)
    for path in db.scalars(
        select(CoregJob.target_image)
        .where(CoregJob.status.in_(["completed", "running", "queued"]))
    ).all()
    if path
   }

    for raw_target in request.target_paths:
        log.info("Processing requested target input=%s", raw_target)
        try:
            target_path = resolve_input_path(settings.target_root, raw_target)
        except ValueError as exc:
            log.warning("Rejected target input=%s reason=%s", raw_target, exc)
            results.append(
                AutoProcessItemResult(
                    target_path=raw_target,
                    status="failed",
                    reason=str(exc),
                )
            )
            continue

        if not target_path.exists():
            log.warning("Target file missing target_path=%s", target_path)
            results.append(
                AutoProcessItemResult(
                    target_path=str(target_path),
                    status="failed",
                    reason=f"Target file not found: {target_path}",
                )
            )
            continue
        
        normalized_target = normalize_path(str(target_path))

        if normalized_target in existing_targets:
            log.info(
                "Skipping already processed target=%s",
                target_path
            )

            results.append(
                AutoProcessItemResult(
                    target_path=str(target_path),
                    status="failed",
                    reason="Target image has already been processed."
                )
            )

            continue

        base_path, match_reason = _match_base_for_target(target_path, request.sensor_name)
        if base_path is None:
            log.warning("No base matched for target=%s reason=%s", target_path, match_reason)
            results.append(
                AutoProcessItemResult(
                    target_path=str(target_path),
                    status="failed",
                    reason=match_reason,
                )
            )
            continue

        job = _create_job(
            db,
            target_path=target_path,
            base_path=base_path,
            sensor_name=request.sensor_name
            or infer_sensor_label(str(target_path))
            or "unknown",
        )
        db.commit()
        
        log.info("Queued job_no=%s for target=%s base=%s", job.job_no, target_path, base_path)
        
        _process_job(job, target_path, base_path, db)
        
        db.refresh(job)

        results.append(
            AutoProcessItemResult(
                target_path=str(target_path),
                status=job.status,
                job_no=job.job_no,
                base_path=job.reference_image,
                sensor_name=job.sensor_name,
                reason=match_reason,
            )
        )

    created_count = len([item for item in results if item.status == "completed"])
    failed_count = len([item for item in results if item.status == "failed"])
    overall_status = "completed" if created_count and not failed_count else "partial" if created_count else "failed"
    log.info(
        "Auto process finished status=%s created_count=%d failed_count=%d",
        overall_status,
        created_count,
        failed_count,
    )

    return AutoProcessResponse(
        # batch_id=batch_id,
        status=overall_status,
        created_count=created_count,
        failed_count=failed_count,
        items=results,
    )


@router.post("/process", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def submit_job(
    request: JobCreateRequest,
    db: Session = Depends(get_db),
):
    log.info(
        "Manual job requested target=%s base=%s sensor=%s use_custom_params=%s",
        request.target_path,
        request.base_path,
        request.sensor_name or "none",
        request.use_custom_params,
    )

    # Validate custom parameters mode: only one target allowed
    if request.use_custom_params and not request.custom_params:
        raise HTTPException(
            status_code=400,
            detail="Custom parameters enabled but no custom_params provided.",
        )

    target_path = resolve_input_path(settings.target_root, request.target_path)

    if not target_path.exists():
        raise HTTPException(status_code=400, detail=f"Target file not found: {target_path}")

    base_path = (
        resolve_input_path(settings.base_root, request.base_path)
        if request.base_path
        else _match_base_for_target(target_path, request.sensor_name)[0]
    )

    if base_path is None:
        raise HTTPException(status_code=400, detail="No matching base image found.")

    log.info("Manual job resolved target=%s base=%s", target_path, base_path)

    job = _create_job(
        db,
        target_path=target_path,
        base_path=base_path,
        sensor_name=request.sensor_name or infer_sensor_label(str(target_path)) or "unknown",
    )

    db.commit()

    # Convert custom params to dict if provided
    custom_params = None
    if request.use_custom_params and request.custom_params:
        custom_params = request.custom_params.model_dump()

    _process_job(job, target_path, base_path, db, custom_params)

    db.refresh(job)

    log.info("Manual job completed job_no=%s status=%s", job.job_no, job.status)

    return _job_to_response(job)


@router.get("", response_model=list[JobResponse])
async def list_jobs(
    status: str | None = Query(None),
    sensor_name: str | None = Query(None),
    search: str | None = Query(None),
    db: Session = Depends(get_db),
):
    stmt = select(CoregJob).order_by(
        CoregJob.job_no.desc()
    )

    jobs = list(db.scalars(stmt))

    if status:
        jobs = [
            job
            for job in jobs
            if job.status == status
        ]

    if sensor_name:
        jobs = [
            job
            for job in jobs
            if job.sensor_name == sensor_name
        ]

    if search:
        query = search.lower()

        jobs = [
            job
            for job in jobs
            if query in job.target_image.lower()
            or query in str(job.job_no)
        ]

    return [
        _job_to_response(job)
        for job in jobs
    ]






@router.patch("/{job_no}/cancel", response_model=JobDetailResponse)
async def cancel_job(
    job_no: int,
    db: Session = Depends(get_db),
):
    job = db.scalar(
        select(CoregJob).where(
            CoregJob.job_no == job_no
        )
    )

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found.",
        )

    if job.status in {"completed", "cancelled"}:
        raise HTTPException(
            status_code=400,
            detail="Job is already finished.",
        )

    job.status = "cancelled"
    job.stage = "cancelled"
    job.completed_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(job)

    return _job_to_detail(job)