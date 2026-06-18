from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from api.db import get_db
from api.config import settings
from api.models import SchedulerConfiguration, CoregistrationJob, FolderInventory
from api.schemas.scheduler import PeriodicityRequest, AutoscanResponse
from api.utils import list_image_files, calculate_folder_size
from api.routers.jobs import _match_base_for_target, _create_job, _process_job
from api.folder_inventory_service import has_folder_changed, sync_all_folders

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
        db.scalars(select(SchedulerConfiguration))
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
    """Ensure default scheduler configurations exist.
    
    Also performs startup sync of folder inventory for all configured
    target folders to auto-create inventory records.
    """
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
    
    # Startup sync: create inventory records for all existing folders
    _sync_folder_inventory_at_startup(db)


def _sync_folder_inventory_at_startup(db: Session) -> None:
    """Sync folder inventory for all configured root paths at startup.
    
    Auto-creates FolderInventory records for folders that don't exist
    in DB yet. This ensures no manual initialization is required.
    """
    configs = list(db.scalars(select(SchedulerConfiguration)))
    for config in configs:
        root_path = Path(config.folder_path)
        if root_path.exists():
            # Sync all subfolders under this root
            sync_all_folders(db, root_path)
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
@router.post(
    "/autoscan",
    response_model=AutoscanResponse,
    status_code=status.HTTP_200_OK,
)
async def trigger_autoscan(
    db: Session = Depends(get_db),
):
    try:
        _ensure_default_configs(db)

        configs = list(
            db.scalars(
                select(SchedulerConfiguration).where(
                    SchedulerConfiguration.enabled.is_(True)
                )
            )
        )

        if not configs:
            return AutoscanResponse(
                status="ok",
                scanned_folders=[],
                new_files_found=[],
                jobs_started=[],
                message="No enabled scheduler configs found",
            )

        now = datetime.now(timezone.utc)

        def normalize_path(path: str) -> str:
            return str(Path(path).resolve()).replace("\\", "/").lower()

        # --------------------------------------------------
        # Existing processed targets
        # --------------------------------------------------
        db_targets = db.scalars(
            select(CoregistrationJob.target_image)
        ).all()

        existing_targets = {
            normalize_path(path)
            for path in db_targets
            if path and str(path).strip()
        }

        print(
            f"Found {len(existing_targets)} existing targets in DB"
        )

        scanned_folders: list[str] = []
        discovered: list[str] = []
        new_files: list[str] = []
        jobs_started: list[int] = []

        # ==================================================
        # Scheduler configs
        # ==================================================
        for config in configs:

            # ----------------------------------------------
            # Respect interval
            # ----------------------------------------------
            if config.last_scan_at:

                elapsed_seconds = (
                    now - config.last_scan_at
                ).total_seconds()

                required_seconds = (
                    config.scan_interval_minutes * 60
                )

                if elapsed_seconds < required_seconds:

                    remaining = (
                        required_seconds - elapsed_seconds
                    )

                    print(
                        f"Skipping scheduler "
                        f"{config.id}. "
                        f"{remaining:.0f}s remaining."
                    )

                    continue

            root_folder = Path(config.folder_path)

            if not root_folder.exists():

                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Folder does not exist: "
                        f"{config.folder_path}"
                    ),
                )

            if not root_folder.is_dir():

                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Path is not a directory: "
                        f"{config.folder_path}"
                    ),
                )

            # ----------------------------------------------
            # Auto-create inventory rows
            # ----------------------------------------------
            sync_all_folders(
                db=db,
                root_path=root_folder,
            )

            # ----------------------------------------------
            # Iterate child folders
            # ----------------------------------------------
            for folder in sorted(root_folder.iterdir()):

                if not folder.is_dir():
                    continue

                scanned_folders.append(str(folder))

                should_process, inventory = (
                    has_folder_changed(
                        db=db,
                        folder_path=folder,
                    )
                )

                if not should_process:

                    print(
                        f"[SKIP] {folder.name} "
                        f"(no changes detected)"
                    )

                    continue

                print(
                    f"[PROCESS] {folder.name} "
                    f"(folder changed)"
                )

                # ------------------------------------------
                # Discover TIFF files
                # ------------------------------------------
                all_images = list(
                    list_image_files(
                        folder,
                        recursive=True,
                    )
                )

                discovered.extend(
                    str(img)
                    for img in all_images
                )

                print(
                    f"{folder.name}: "
                    f"{len(all_images)} image(s) found"
                )

                # ------------------------------------------
                # Existing processing logic
                # ------------------------------------------
                for img_path in all_images:

                    img_str = str(img_path)

                    normalized_img = normalize_path(
                        img_str
                    )

                    if (
                        normalized_img
                        in existing_targets
                    ):
                        continue

                    new_files.append(img_str)

                    satellite_name = (
                        folder.name.split("_")[0]
                        if "_" in folder.name
                        else folder.name
                    )

                    base_path, match_reason = (
                        _match_base_for_target(
                            img_path,
                            satellite_name,
                        )
                    )

                    if base_path is None:

                        print(
                            f"No matching base found "
                            f"for {img_str}"
                        )

                        continue

                    job = _create_job(
                        db=db,
                        target_path=img_path,
                        base_path=base_path,
                        sensor_name=satellite_name,
                    )

                    db.commit()

                    existing_targets.add(
                        normalized_img
                    )

                    print(
                        f"Starting job "
                        f"{job.job_no}"
                    )

                    _process_job(
                        job,
                        img_path,
                        base_path,
                        db,
                    )

                    db.refresh(job)

                    jobs_started.append(
                        job.job_no
                    )

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
            ),
        )

    except Exception:
        import traceback

        traceback.print_exc()
        raise