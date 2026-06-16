from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from api.db import get_db
from api.config import settings
from api.models import CoregSchedulerConfig
from api.schemas.scheduler import SchedulerConfigRequest, SchedulerConfigResponse, SchedulerStatusResponse
from api.utils import list_image_files

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


@router.get("/config", response_model=SchedulerStatusResponse)
async def get_scheduler_configuration(db: Session = Depends(get_db)):
    _ensure_default_configs(db)
    configs = list(db.scalars(select(SchedulerConfig).order_by(SchedulerConfig.id.asc())))
    return SchedulerStatusResponse(
        enabled=any(config.enabled for config in configs) if configs else True,
        last_scan_at=max((config.last_scan_at for config in configs if config.last_scan_at), default=None),
        configs=[SchedulerConfigResponse.model_validate(config) for config in configs],
    )


@router.put("/config", response_model=SchedulerStatusResponse)
async def update_scheduler_configuration(request: SchedulerConfigRequest, db: Session = Depends(get_db)):
    db.execute(delete(SchedulerConfig))
    for folder in request.folders:
        db.add(
            SchedulerConfig(
                folder_path=folder.path,
                recursive=folder.recursive,
                sensor_hint=folder.sensor_hint,
                interval_minutes=request.interval_minutes,
                min_overlap_pct=request.min_overlap_pct,
                max_cloud_cover_pct=request.max_cloud_cover_pct,
                enabled=request.enabled,
                last_scan_at=None,
                updated_at=datetime.now(timezone.utc),
            )
        )
    db.commit()
    return await get_scheduler_configuration(db)


@router.post("/scan", status_code=status.HTTP_200_OK)
async def trigger_manual_folders_scan(db: Session = Depends(get_db)):
    _ensure_default_configs(db)
    configs = list(db.scalars(select(SchedulerConfig)))
    if not configs:
        return {"status": "ok", "scanned_folders": [], "discovered_files": []}

    discovered: list[str] = []
    now = datetime.now(timezone.utc)
    for config in configs:
        folder = Path(config.folder_path)
        if not folder.exists():
            raise HTTPException(status_code=400, detail=f"Folder does not exist: {config.folder_path}")
        discovered.extend(str(path) for path in list_image_files(folder, recursive=config.recursive))
        config.last_scan_at = now
        config.updated_at = now

    db.commit()
    return {
        "status": "ok",
        "scanned_folders": [config.folder_path for config in configs],
        "discovered_files": discovered,
    }


@router.post("/toggle", response_model=SchedulerStatusResponse)
async def toggle_scheduler(active: bool, db: Session = Depends(get_db)):
    _ensure_default_configs(db)
    configs = list(db.scalars(select(SchedulerConfig)))
    for config in configs:
        config.enabled = active
        config.updated_at = datetime.now(timezone.utc)
    db.commit()
    return await get_scheduler_configuration(db)
