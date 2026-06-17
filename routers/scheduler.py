from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from api.db import get_db
from api.config import settings
from api.models import SchedulerConfig, CoregJob
from api.schemas.scheduler import PeriodicityRequest, AutoscanResponse
from api.utils import list_image_files
from api.routers.jobs import _match_base_for_target, _create_job, _process_job

router = APIRouter(prefix="/scheduler", tags=["Scheduler"])


def _normalize_root_path(raw_path: str) -> str:
    normalized = raw_path.replace("\\", "/").rstrip("/")
    return normalized


def _ensure_default_configs(db: Session) -> None:
    if db.scalar(select(SchedulerConfig.id).limit(1)) is not None:
        configs = list(db.scalars(select(SchedulerConfig)))
        changed = False
        for config in configs:
            normalized = _normalize_root_path(config.folder_path)
            if config.sensor_hint == "target" or normalized in {"d:/target", "e:/target", "e:/ashishworkspace/coregistration-demo/target"}:
                config.folder_path = str(settings.target_root)
                config.sensor_hint = "target"
                changed = True
            elif config.sensor_hint == "base" or normalized in {"d:/base", "e:/base", "e:/ashishworkspace/coregistration-demo/base"}:
                config.folder_path = str(settings.base_root)
                config.sensor_hint = "base"
                changed = True
        if changed:
            db.commit()
        return

    db.add_all(
        [
            SchedulerConfig(folder_path=str(settings.target_root), recursive=True, sensor_hint="target"),
            SchedulerConfig(folder_path=str(settings.base_root), recursive=True, sensor_hint="base"),
        ]
    )
    db.commit()


@router.post("/periodicity", status_code=status.HTTP_200_OK)
async def set_periodicity(request: PeriodicityRequest, db: Session = Depends(get_db)):
    """Set the scan periodicity (interval in minutes)."""
    _ensure_default_configs(db)
    configs = list(db.scalars(select(SchedulerConfig)))
    if not configs:
        raise HTTPException(status_code=404, detail="No scheduler config found")
    
    for config in configs:
        config.interval_minutes = request.interval_minutes
        config.updated_at = datetime.now(timezone.utc)
    
    db.commit()
    return {
        "status": "ok",
        "interval_minutes": request.interval_minutes,
        "message": f"Periodicity set to {request.interval_minutes} minute(s)"
    }


@router.post("/autoscan", response_model=AutoscanResponse, status_code=status.HTTP_200_OK)
async def trigger_autoscan(db: Session = Depends(get_db)):
    """Trigger autoscan based on saved periodicity and start coreg process for new files.
    
    This endpoint:
    1. Scans the target folder for image files
    2. Filters out target images that are already completed (status='completed' in coreg_job)
    3. For each new target image, finds a matching base image and starts the coregistration process
    """
    _ensure_default_configs(db)
    configs = list(db.scalars(select(SchedulerConfig).where(SchedulerConfig.enabled == True)))
    
    if not configs:
        return AutoscanResponse(
            status="ok",
            scanned_folders=[],
            new_files_found=[],
            jobs_started=[],
            message="No enabled scheduler configs found"
        )
    
    # Get all completed target images to exclude them
    completed_targets = set(
        db.scalars(
            select(CoregJob.target_image).where(CoregJob.status == "completed")
        ).all()
    )
    
    discovered: list[str] = []
    new_files: list[str] = []
    jobs_started: list[int] = []
    now = datetime.now(timezone.utc)
    
    for config in configs:
        if config.sensor_hint != "target":
            continue
            
        folder = Path(config.folder_path)
        if not folder.exists():
            raise HTTPException(status_code=400, detail=f"Folder does not exist: {config.folder_path}")
        
        all_images = list(list_image_files(folder, recursive=config.recursive))
        discovered.extend(str(path) for path in all_images)
        
        # Filter out already completed targets
        for img_path in all_images:
            img_str = str(img_path)
            if img_str not in completed_targets:
                new_files.append(img_str)
                
                # Find matching base and start coregistration
                base_path, match_reason = _match_base_for_target(img_path, config.sensor_hint)
                if base_path is None:
                    continue
                
                # Create and process job
                job = _create_job(
                    db,
                    target_path=img_path,
                    base_path=base_path,
                    sensor_name=config.sensor_hint or "unknown",
                )
                db.commit()
                
                # Start the coregistration process
                _process_job(job, img_path, base_path, db)
                
                db.refresh(job)
                jobs_started.append(job.job_no)
        
        config.last_scan_at = now
        config.updated_at = now
    
    db.commit()
    
    return AutoscanResponse(
        status="ok",
        scanned_folders=[config.folder_path for config in configs if config.sensor_hint == "target"],
        new_files_found=new_files,
        jobs_started=jobs_started,
        message=f"Found {len(new_files)} new file(s), started {len(jobs_started)} job(s)"
    )
