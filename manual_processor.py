from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from models import CoregistrationJob
from services.job_service import create_job
from utils import is_file_already_processed


class FileAlreadyProcessedError(Exception):
    pass


def process_manual_file_upload(
    db: Session,
    file_path: Path,
    reference_image_path: Path,
    sensor_name: str,
) -> CoregistrationJob:
    if not file_path.exists():
        raise ValueError(f"File not found: {file_path}")
    if not reference_image_path.exists():
        raise ValueError(f"Reference image not found: {reference_image_path}")
    if is_file_already_processed(db, file_path):
        raise FileAlreadyProcessedError(f"File already processed: {file_path.resolve()}")

    job = create_job(db, file_path, reference_image_path, sensor_name or "unknown")
    db.flush()
    return job
