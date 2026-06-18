"""
Manual file selection and upload handler.

Implements the MANUAL FLOW:
1. User selects TIFF file
2. Check CoregistrationJob (via is_file_already_processed)
3. If already processed, return error
4. Otherwise, create CoregistrationJob
"""

from __future__ import annotations

from pathlib import Path
from sqlalchemy.orm import Session

from api.db import SessionLocal
from api.models import CoregJob
from api.utils import is_file_already_processed


class FileAlreadyProcessedError(Exception):
    """Raised when a file has already been processed."""
    pass


def process_manual_file_upload(
    db: Session,
    file_path: Path,
    reference_image_path: Path,
    sensor_name: str,
) -> CoregJob:
    """
    Handle manual file selection and create coregistration job.
    
    Flow:
    1. Check if file already processed (duplicate detection)
    2. If yes, raise FileAlreadyProcessedError
    3. If no, create CoregJob
    
    Args:
        db: Database session
        file_path: Path to selected TIFF (target image)
        reference_image_path: Path to reference image
        sensor_name: Sensor identifier (e.g., "sentinel-2", "cartosat")
    
    Returns:
        Created CoregJob instance
    
    Raises:
        FileAlreadyProcessedError: If file already processed
        ValueError: If file doesn't exist or is invalid
    
    Example:
        from api.db import SessionLocal
        from pathlib import Path
        from api.manual_processor import process_manual_file_upload
        
        db = SessionLocal()
        try:
            job = process_manual_file_upload(
                db,
                Path("/mnt/TARGET/C2A_PAK/image.tif"),
                Path("/mnt/REFERENCE/ref.tif"),
                "cartosat"
            )
            print(f"Created job: {job.id}")
        except FileAlreadyProcessedError:
            print("File already processed")
        finally:
            db.close()
    """
    # Validate inputs
    if not file_path.exists():
        raise ValueError(f"File not found: {file_path}")
    
    if not reference_image_path.exists():
        raise ValueError(f"Reference image not found: {reference_image_path}")
    
    # Check for duplicates using shared helper
    if is_file_already_processed(db, file_path):
        raise FileAlreadyProcessedError(
            f"File already processed: {file_path.resolve()}"
        )
    
    # Create job (uses existing _create_job logic)
    job = _create_job(
        db,
        target_image_path=file_path,
        reference_image_path=reference_image_path,
        sensor_name=sensor_name,
    )
    
    return job


def _create_job(
    db: Session,
    target_image_path: Path,
    reference_image_path: Path,
    sensor_name: str,
) -> CoregJob:
    """
    Create a CoregJob record.
    
    This is the existing _create_job() logic from the service.
    DO NOT MODIFY - keeps existing processing pipeline intact.
    
    Args:
        db: Database session
        target_image_path: Path to target TIFF
        reference_image_path: Path to reference image
        sensor_name: Sensor name/identifier
    
    Returns:
        Created CoregJob instance
    """
    # Placeholder: integrate with existing _create_job() implementation
    # This should:
    # - Create CoregJob record with status="queued"
    # - Store normalized paths
    # - Return job instance
    
    # For now, raise NotImplementedError
    raise NotImplementedError("_create_job must be integrated with existing service")
