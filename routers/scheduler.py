from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from db import get_db
from scheduler_service import run_scheduled_scan
from schemas.scheduler import AutoscanResponse, PeriodicityRequest
from services.scheduler_config import (
    ensure_default_scheduler_config,
    list_scheduler_configs,
    primary_config,
    reset_scan_timer,
    utcnow,
)

router = APIRouter(prefix="/scheduler", tags=["Scheduler"])


@router.get("/config", status_code=status.HTTP_200_OK)
def get_scheduler_config(db: Session = Depends(get_db)):
    configs = list_scheduler_configs(db)
    primary = primary_config(configs)
    return {
        "enabled": primary.enabled if primary else True,
        "scan_interval_minutes": primary.scan_interval_minutes if primary else 60,
        "last_scan_at": primary.last_scan_at.isoformat() if primary and primary.last_scan_at else None,
        "configs": [
            {
                "id": c.id,
                "enabled": c.enabled,
                "folder_path": c.folder_path,
                "scan_interval_minutes": c.scan_interval_minutes,
                "last_scan_at": c.last_scan_at.isoformat() if c.last_scan_at else None,
            }
            for c in configs
        ],
    }


@router.post("/periodicity", status_code=status.HTTP_200_OK)
async def set_periodicity(request: PeriodicityRequest, db: Session = Depends(get_db)):
    configs = list_scheduler_configs(db)
    now = utcnow()
    for config in configs:
        config.scan_interval_minutes = request.interval_minutes
        if request.enabled is not None:
            config.enabled = request.enabled
    reset_scan_timer(db, configs, now)
    db.commit()
    return {
        "status": "ok",
        "interval_minutes": request.interval_minutes,
        "enabled": request.enabled,
        "message": f"Periodicity set to {request.interval_minutes} minute(s). Next scan after interval.",
    }


@router.post("/toggle", status_code=status.HTTP_200_OK)
async def toggle_scheduler(active: bool = Query(...), db: Session = Depends(get_db)):
    configs = list_scheduler_configs(db)
    for config in configs:
        config.enabled = active
    db.commit()
    return {"status": "ok", "enabled": active}


@router.post("/autoscan", response_model=AutoscanResponse, status_code=status.HTTP_200_OK)
async def trigger_autoscan(force: bool = Query(False)):
    result = run_scheduled_scan(force=force)
    return AutoscanResponse(**{k: result[k] for k in ("status", "scanned_folders", "new_files_found", "jobs_started", "message")})


@router.post("/scan", response_model=AutoscanResponse, status_code=status.HTTP_200_OK)
async def manual_scan():
    result = run_scheduled_scan(force=True)
    return AutoscanResponse(**{k: result[k] for k in ("status", "scanned_folders", "new_files_found", "jobs_started", "message")})
