from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config import settings
from db import get_db
from models import CoregistrationJob

router = APIRouter(prefix="/system", tags=["System"])


@router.get("/health")
async def get_system_health(db: Session = Depends(get_db)):
    job_count = db.scalar(select(func.count()).select_from(CoregistrationJob)) or 0
    return {
        "status": "healthy",
        "database": "connected",
        "job_count": job_count,
        "paths": {
            "target_root": str(settings.target_root),
            "base_root": str(settings.base_root),
            "output_root": str(settings.output_root),
            "staging_root": str(settings.staging_root),
            "log_root": str(settings.log_root),
        },
        "path_existence": {
            "target_root": Path(settings.target_root).exists(),
            "base_root": Path(settings.base_root).exists(),
            "output_root": Path(settings.output_root).exists(),
        },
    }


@router.post("/reconnect")
async def reconnect():
    return {"status": "ok", "message": "SQLAlchemy session management handles reconnects automatically."}
