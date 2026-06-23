from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from coreg_service import run_coregistration_and_cog
from models import (
    CoregistrationJob,
    CoregistrationMetrics,
    CoregistrationParameters,
    CoregistrationPixelSize,
    OverallStatistics,
    SystemPerformanceMetrics,
)
from schemas.job import JobDetailResponse, JobResponse
from utils import (
    ensure_dir,
    gdal_pixel_size,
    geo_overlap_metrics,
    infer_sensor_label,
    list_image_files,
    normalize_path,
    parse_satellite_country_folder,
    sensor_from_folder_name,
    shared_token_count,
)

log = logging.getLogger("api.jobs")


def match_base_for_target(target_path: Path, preferred_sensor: str | None = None) -> tuple[Path | None, str]:
    base_files = list_image_files(settings.base_root, recursive=True)
    if not base_files:
        log.warning("No base files found under %s", settings.base_root)
        return None, "No base image found in BASE_ROOT."

    sensor_hint = infer_sensor_label(preferred_sensor) if preferred_sensor else None
    scored_candidates: list[dict[str, object]] = []
    log.info(
        "Matching target=%s sensor_hint=%s against %d base files",
        target_path,
        sensor_hint or "none",
        len(base_files),
    )

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
        return None, f"No geospatial overlap found for target '{target_path.name}' in BASE_ROOT."

    geo_candidates = [item for item in scored_candidates if item["has_geo_match"]]
    candidate_pool = geo_candidates if geo_candidates else scored_candidates

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
        reason = (
            f"matched by {crs_text}, bbox overlap {metrics['bbox_overlap_pct']}%, "
            f"extent intersection {metrics['extent_intersection_pct']}%, "
            f"geometry overlap {metrics['geometry_overlap_pct']}%, "
            f"lat/lon overlap {metrics['latlon_overlap_pct']}%."
        )
    else:
        reason = f"used fallback token/sensor match for target '{target_path.stem}' against base '{chosen.stem}'."

    log.info("Selected base=%s for target=%s reason=%s", chosen, target_path, reason)
    return chosen, reason


def build_job_output_paths(job_number: int, target_path: Path) -> tuple[Path, Path, Path]:
    folder_name = target_path.parent.name
    if parse_satellite_country_folder(folder_name):
        output_root = ensure_dir(settings.output_root / folder_name)
    else:
        output_root = ensure_dir(settings.output_root)

    coreg_dir = ensure_dir(output_root / "coreg")
    cog_dir = ensure_dir(output_root / "cog")
    coreg_output = coreg_dir / f"{target_path.stem}_coregistered_{job_number}.tif"
    cog_output = cog_dir / f"{target_path.stem}_cog_{job_number}.tif"
    return output_root, coreg_output, cog_output


def create_job(db: Session, target_path: Path, base_path: Path, sensor_type: str) -> CoregistrationJob:
    job = CoregistrationJob(
        status="queued",
        processing_stage="queued",
        sensor_type=sensor_type,
        reference_image_path=normalize_path(base_path),
        target_image_path=normalize_path(target_path),
        processing_duration_seconds=0.0,
        created_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.flush()

    _, coreg_output, cog_output = build_job_output_paths(job.job_number, target_path)
    job.coregistered_output_path = str(coreg_output)
    job.cloud_optimized_output_path = str(cog_output)
    db.flush()
    return job


def job_to_response(job: CoregistrationJob) -> JobResponse:
    return JobResponse.model_validate({
        "job_number": job.job_number or 0,
        "status": job.status,
        "processing_stage": job.processing_stage,
        "sensor_type": job.sensor_type,
        "reference_image_path": job.reference_image_path,
        "target_image_path": job.target_image_path,
        "coregistered_output_path": job.coregistered_output_path,
        "cloud_optimized_output_path": job.cloud_optimized_output_path,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "processing_duration_seconds": job.processing_duration_seconds,
        "error_message": job.error_message,
    })


def job_to_detail(job: CoregistrationJob) -> JobDetailResponse:
    return JobDetailResponse.model_validate(job_to_response(job).model_dump())


def load_existing_target_paths(db: Session, *, active_only: bool = False) -> set[str]:
    stmt = select(CoregistrationJob.target_image_path)
    if active_only:
        stmt = stmt.where(CoregistrationJob.status.in_(["completed", "running", "queued"]))
    return {normalize_path(path) for path in db.scalars(stmt).all() if path}


def create_metrics_for_job(db: Session, job: CoregistrationJob, result: dict) -> None:
    import psutil

    if db.scalar(select(CoregistrationMetrics).where(CoregistrationMetrics.job_id == job.id)):
        return

    metrics = CoregistrationMetrics(job_id=job.id, quality_rating=result.get("quality"))
    db.add(metrics)
    db.flush()

    params = result.get("parameters", {})
    window_size = params.get("window_size", (0, 0))
    window_width = window_size[0] if isinstance(window_size, tuple) else 0
    window_height = window_size[1] if isinstance(window_size, tuple) else 0

    db.add(CoregistrationParameters(
        metrics_id=metrics.id,
        reference_image_path=job.reference_image_path,
        target_image_path=job.target_image_path,
        grid_resolution=params.get("grid_res", 0),
        window_width=window_width,
        window_height=window_height,
        maximum_shift_pixels=params.get("max_shift", 0.0),
        tiepoint_filter_level=params.get("tieP_filter_level", 3),
        minimum_reliability_percent=params.get("min_reliability", 40.0),
        ransac_maximum_outliers=params.get("rs_max_outlier", 10),
        cpu_cores_used=params.get("CPUs", 12),
        output_format=params.get("fmt_out", "GTiff"),
        output_directory=params.get("path_out", str(job.coregistered_output_path)),
        resampling_algorithm_calculation=params.get("resamp_alg_calc", "nearest"),
        resampling_algorithm_deshift=params.get("resamp_alg_deshift", "nearest"),
        match_ground_sample_distance=params.get("match_gsd", True),
        quiet_mode=params.get("q", False),
    ))

    try:
        from osgeo import gdal
        tgt_ds = gdal.Open(job.target_image_path)
        out_ds = gdal.Open(job.coregistered_output_path) if job.coregistered_output_path else None
        target_gt = tgt_ds.GetGeoTransform() if tgt_ds else (0, 0, 0, 0, 0, 0)
        output_gt = out_ds.GetGeoTransform() if out_ds else (0, 0, 0, 0, 0, 0)
        db.add(CoregistrationPixelSize(
            metrics_id=metrics.id,
            target_pixel_size_x=abs(target_gt[1]) if target_gt else 0.0,
            target_pixel_size_y=abs(target_gt[5]) if target_gt else 0.0,
            output_pixel_size_x=abs(output_gt[1]) if output_gt else 0.0,
            output_pixel_size_y=abs(output_gt[5]) if output_gt else 0.0,
        ))
    except Exception:
        pass

    process = psutil.Process()
    vmem = psutil.virtual_memory()
    mem_info = process.memory_info()
    db.add(SystemPerformanceMetrics(
        metrics_id=metrics.id,
        cpu_usage_percent=psutil.cpu_percent(interval=0.1),
        cpu_cores_count=psutil.cpu_count(logical=False) or 1,
        ram_total_gb=vmem.total / (1024**3),
        ram_available_gb=vmem.available / (1024**3),
        ram_used_gb=vmem.used / (1024**3),
        ram_usage_percent=vmem.percent,
        process_memory_gb=mem_info.rss / (1024**3),
        disk_read_mb=getattr(process.io_counters(), "read_bytes", 0) / (1024**2) if hasattr(process, "io_counters") else 0.0,
        disk_write_mb=getattr(process.io_counters(), "write_bytes", 0) / (1024**2) if hasattr(process, "io_counters") else 0.0,
        process_thread_count=process.num_threads(),
    ))

    valid_points = int(result.get("valid_points", 0))
    total_tiepoints = int(result.get("matched_points", 0))
    invalid_points = max(0, total_tiepoints - valid_points)
    valid_percent = (valid_points / total_tiepoints * 100.0) if total_tiepoints else 0.0

    db.add(OverallStatistics(
        metrics_id=metrics.id,
        total_tiepoints=total_tiepoints,
        valid_tiepoints=valid_points,
        invalid_tiepoints=invalid_points,
        valid_percent=valid_percent,
        invalid_percent=100.0 - valid_percent if total_tiepoints else 0.0,
        rmse_x=0.0, rmse_y=0.0, rmse_magnitude=0.0, rmse_pixels=0.0,
        mse_x=0.0, mse_y=0.0, mae_x=0.0, mae_y=0.0,
        shift_mean=0.0, shift_median=0.0, shift_std=0.0, shift_min=0.0, shift_max=0.0,
        angle_mean=0.0, ssim_mean=0.0, reliability_mean=0.0, reliability_median=0.0,
    ))
    job.metrics = metrics
    db.flush()


def process_job(
    job: CoregistrationJob,
    target_path: Path,
    base_path: Path,
    db: Session,
    custom_params: dict | None = None,
) -> None:
    if job.coregistered_output_path:
        run_root = Path(job.coregistered_output_path).parent.parent
    else:
        run_root, _, _ = build_job_output_paths(job.job_number, target_path)

    start = datetime.now(timezone.utc)
    job.status = "running"
    job.processing_stage = "coregistration"
    job.started_at = start
    db.commit()

    try:
        result = run_coregistration_and_cog(
            base_path,
            target_path,
            run_root,
            custom_params,
            output_suffix=f"_{job.job_number}",
        )
        job.coregistered_output_path = result["coreg_output"]
        job.cloud_optimized_output_path = result["cog_output"]
        job.status = "completed"
        job.processing_stage = "completed"
        job.completed_at = datetime.now(timezone.utc)
        create_metrics_for_job(db, job, result)
        job.processing_duration_seconds = round((job.completed_at - start).total_seconds(), 2)
        db.commit()
    except Exception as exc:
        db.rollback()
        log.exception("Job failed job_number=%s target=%s", job.job_number, target_path)
        job.status = "failed"
        job.processing_stage = "failed"
        job.error_message = str(exc)
        job.completed_at = datetime.now(timezone.utc)
        job.processing_duration_seconds = round((job.completed_at - start).total_seconds(), 2)
        db.commit()


def resolve_sensor_type(target_path: Path, preferred: str | None = None) -> str:
    return preferred or sensor_from_folder_name(target_path.parent.name) or infer_sensor_label(str(target_path)) or "unknown"
