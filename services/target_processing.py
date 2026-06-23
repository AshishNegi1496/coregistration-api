from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from models import CoregistrationJob
from services.job_service import create_job, match_base_for_target, process_job, resolve_sensor_type
from utils import normalize_path


def process_new_target_file(
    db: Session,
    target_path: Path,
    existing_targets: set[str],
    preferred_sensor: str | None = None,
) -> tuple[CoregistrationJob | None, str | None]:
    """Create and run a job for a new target file. Returns (job, error_reason)."""
    normalized = normalize_path(target_path)
    if normalized in existing_targets:
        return None, "already_processed"

    base_path, reason = match_base_for_target(target_path, preferred_sensor)
    if base_path is None:
        return None, reason

    job = create_job(
        db=db,
        target_path=target_path,
        base_path=base_path,
        sensor_type=resolve_sensor_type(target_path, preferred_sensor),
    )
    db.commit()
    process_job(job, target_path, base_path, db)
    db.refresh(job)
    existing_targets.add(normalized)
    return job, None
