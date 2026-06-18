from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from api.db import get_db
from api.config import settings
from api.models import SchedulerConfiguration, CoregistrationJob
from api.schemas.scheduler import PeriodicityRequest, AutoscanResponse
from api.utils import list_image_files
from api.routers.jobs import _match_base_for_target, _create_job, _process_job

router = APIRouter(prefix="/scheduler", tags=["Scheduler"])


def _normalize_root_path(raw_path: str) -> str:
    normalized = raw_path.replace("\\", "/").rstrip("/")
    return normalized


@router.get("/config", status_code=status.HTTP_200_OK)
def get_scheduler_config(
    db: Session = Depends(get_db)
):
    _ensure_default_configs(db)

    configs = list(
        db.scalars(select(SchedulerConfig))
    )

    return {
        "configs": [
            {
                "id": c.id,
                "enabled": c.enabled,
                "folder_path": c.folder_path,
                "recursive": c.recursive,
                "sensor_hint": c.sensor_hint,
                "interval_minutes": c.interval_minutes,
            }
            for c in configs
        ]
    }

def _ensure_default_configs(db: Session) -> None:
    if db.scalar(select(SchedulerConfiguration.id).limit(1)) is not None:
        configs = list(db.scalars(select(SchedulerConfiguration)))
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
            SchedulerConfiguration(folder_path=str(settings.target_root), recursive=True, sensor_hint="target"),
            SchedulerConfiguration(folder_path=str(settings.base_root), recursive=True, sensor_hint="base"),
        ]
    )
    db.commit()


@router.post("/periodicity", status_code=status.HTTP_200_OK)
async def set_periodicity(
    request: PeriodicityRequest,
    db: Session = Depends(get_db)
):
    """Set scan periodicity and start countdown from now."""

    _ensure_default_configs(db)

    configs = list(db.scalars(select(SchedulerConfiguration)))

    if not configs:
        raise HTTPException(
            status_code=404,
            detail="No scheduler config found"
        )

    now = datetime.now(timezone.utc)

    for config in configs:
        config.interval_minutes = request.interval_minutes

        # Reset timer so first scan happens AFTER interval
        config.last_scan_at = now

        config.updated_at = now

    db.commit()

    return {
        "status": "ok",
        "interval_minutes": request.interval_minutes,
        "message": (
            f"Periodicity set to {request.interval_minutes} minute(s). "
            f"First scan will run after the interval expires."
        )
    }

@router.post("/autoscan", response_model=AutoscanResponse, status_code=status.HTTP_200_OK)
async def trigger_autoscan(db: Session = Depends(get_db)):
    try:
        _ensure_default_configs(db)

        configs = list(
            db.scalars(
                select(SchedulerConfiguration)
                .where(SchedulerConfiguration.enabled == True)
            )
        )

        if not configs:
            return AutoscanResponse(
                status="ok",
                scanned_folders=[],
                new_files_found=[],
                jobs_started=[],
                message="No enabled scheduler configs found"
            )

        now = datetime.now(timezone.utc)

        def normalize_path(path: str) -> str:
            return str(Path(path).resolve()).replace("\\", "/").lower()

        # Get all previously processed targets
        db_targets = db.scalars(
            select(CoregistrationJob.target_image)
        ).all()

        existing_targets = {
            normalize_path(path)
            for path in db_targets
            if path is not None and str(path).strip()
        }

        print(f"Found {len(existing_targets)} existing targets in DB")

        discovered: list[str] = []
        new_files: list[str] = []
        jobs_started: list[int] = []
        scanned_folders: list[str] = []

        for config in configs:

            if config.sensor_hint != "target":
                continue

            # -----------------------------------------
            # Wait for configured interval
            # -----------------------------------------
            if config.last_scan_at is not None:
                elapsed_seconds = (
                    now - config.last_scan_at
                ).total_seconds()

                required_seconds = (
                    config.interval_minutes * 60
                )

                if elapsed_seconds < required_seconds:
                    remaining = required_seconds - elapsed_seconds

                    print(
                        f"Skipping scan. "
                        f"{remaining:.0f}s remaining before next scan."
                    )
                    continue

            # -----------------------------------------
            # Validate folder
            # -----------------------------------------
            folder = Path(config.folder_path)

            if not folder.exists():
                raise HTTPException(
                    status_code=400,
                    detail=f"Folder does not exist: {config.folder_path}"
                )

            scanned_folders.append(config.folder_path)

            all_images = list(
                list_image_files(
                    folder,
                    recursive=config.recursive
                )
            )

            discovered.extend(
                str(path)
                for path in all_images
            )

            print(f"Discovered {len(all_images)} image(s)")

            # -----------------------------------------
            # Process only new files
            # -----------------------------------------
            for img_path in all_images:

                img_str = str(img_path)

                normalized_img = normalize_path(img_str)

                if normalized_img in existing_targets:
                    print(
                        f"Skipping already processed file: "
                        f"{img_str}"
                    )
                    continue

                new_files.append(img_str)

                base_path, match_reason = _match_base_for_target(
                    img_path,
                    config.sensor_hint
                )

                if base_path is None:
                    print(
                        f"No matching base found for: "
                        f"{img_str}"
                    )
                    continue

                job = _create_job(
                    db,
                    target_path=img_path,
                    base_path=base_path,
                    sensor_name=config.sensor_hint or "unknown",
                )

                db.commit()

                existing_targets.add(normalized_img)

                print(
                    f"Starting job {job.job_no} "
                    f"for {img_str}"
                )

                _process_job(
                    job,
                    img_path,
                    base_path,
                    db
                )

                db.refresh(job)

                jobs_started.append(job.job_no)

            # -----------------------------------------
            # Update scan timestamps
            # -----------------------------------------
            config.last_scan_at = now
            config.updated_at = now

        db.commit()

        return AutoscanResponse(
            status="ok",
            scanned_folders=scanned_folders,
            new_files_found=new_files,
            jobs_started=jobs_started,
            message=(
                f"Found {len(new_files)} new file(s), "
                f"started {len(jobs_started)} job(s)"
            )
        )

    except Exception:
        import traceback
        traceback.print_exc()
        raise
