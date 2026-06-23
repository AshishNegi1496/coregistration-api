from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue

from sqlalchemy import select

from db import SessionLocal
from models import FolderProcessingAudit, FolderSnapshot
from services.target_processing import process_new_target_file
from utils import (
    calculate_folder_size,
    ensure_dir,
    file_signature,
    is_image_file,
    list_image_files,
    normalize_path,
    parse_satellite_country_folder,
)

log = logging.getLogger("api.folder_monitor")


@dataclass
class FileEvent:
    path: Path
    detected_at: datetime


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FolderMonitorService:
    def __init__(self, root_path: Path, poll_interval_seconds: float = 2.0) -> None:
        self.root_path = root_path.resolve()
        self.poll_interval_seconds = poll_interval_seconds
        self.event_queue: Queue[FileEvent] = Queue()
        self.stop_event = threading.Event()
        self.scan_thread: threading.Thread | None = None
        self.worker_thread: threading.Thread | None = None
        self.inflight_files: set[str] = set()
        self.known_files: dict[str, tuple[int, int]] = {}
        self.lock = threading.Lock()

    def start(self) -> None:
        ensure_dir(self.root_path)
        self._bootstrap_scan()
        self.stop_event.clear()
        self.scan_thread = threading.Thread(target=self._scan_loop, daemon=True, name="folder-monitor-scan")
        self.scan_thread.start()
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name="folder-monitor-worker")
        self.worker_thread.start()
        log.info("Folder monitor started for %s", self.root_path)

    def stop(self) -> None:
        self.stop_event.set()
        if self.scan_thread:
            self.scan_thread.join(timeout=10)
        if self.worker_thread:
            self.worker_thread.join(timeout=10)

    def _bootstrap_scan(self) -> None:
        now = _utcnow()
        with SessionLocal() as db:
            known_paths: set[str] = set()
            existing_files: dict[str, tuple[int, int]] = {}
            for folder in self._satellite_country_folders():
                parts = parse_satellite_country_folder(folder.name)
                if not parts:
                    continue
                satellite, country = parts
                known_paths.add(normalize_path(folder))
                self._upsert_snapshot(db, folder, satellite, country, now)
                for image in list_image_files(folder, recursive=True):
                    existing_files[normalize_path(image)] = file_signature(image)
            self._mark_inactive(db, known_paths, now)
            db.commit()
        self.known_files = existing_files

    def _scan_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self._poll_once()
            except Exception:
                log.exception("Folder scan loop error")
            self.stop_event.wait(self.poll_interval_seconds)

    def _poll_once(self) -> None:
        now = _utcnow()
        current_files: dict[str, tuple[int, int]] = {}
        known_paths: set[str] = set()

        with SessionLocal() as db:
            for folder in self._satellite_country_folders():
                parts = parse_satellite_country_folder(folder.name)
                if not parts:
                    continue
                satellite, country = parts
                known_paths.add(normalize_path(folder))
                self._upsert_snapshot(db, folder, satellite, country, now)
                for image in list_image_files(folder, recursive=True):
                    current_files[normalize_path(image)] = file_signature(image)
            self._mark_inactive(db, known_paths, now)
            db.commit()

        previous_files = self.known_files
        self.known_files = current_files
        for file_path, signature in current_files.items():
            if previous_files.get(file_path) != signature:
                self.event_queue.put(FileEvent(path=Path(file_path), detected_at=now))

    def _satellite_country_folders(self) -> list[Path]:
        if not self.root_path.exists():
            return []
        return [
            path for path in sorted(self.root_path.iterdir())
            if path.is_dir() and parse_satellite_country_folder(path.name)
        ]

    def _upsert_snapshot(self, db, folder: Path, satellite: str, country: str, timestamp: datetime) -> None:
        folder_path = normalize_path(folder)
        snapshot = db.scalar(select(FolderSnapshot).where(FolderSnapshot.folder_path == folder_path))
        folder_size = calculate_folder_size(folder) if folder.is_dir() else 0
        try:
            modified_time = datetime.fromtimestamp(folder.stat().st_mtime, tz=timezone.utc)
        except OSError:
            modified_time = timestamp

        if snapshot is None:
            db.add(FolderSnapshot(
                folder_name=folder.name,
                satellite=satellite,
                country=country,
                folder_path=folder_path,
                modified_time=modified_time,
                total_size_bytes=folder_size,
                last_scan_at=timestamp,
                is_active=True,
            ))
            return

        snapshot.folder_name = folder.name
        snapshot.satellite = satellite
        snapshot.country = country
        snapshot.modified_time = modified_time
        snapshot.total_size_bytes = folder_size
        snapshot.last_scan_at = timestamp
        snapshot.is_active = True

    def _mark_inactive(self, db, active_paths: set[str], timestamp: datetime) -> None:
        for snapshot in db.scalars(select(FolderSnapshot)):
            if snapshot.folder_path not in active_paths and snapshot.is_active:
                snapshot.is_active = False
                snapshot.last_scan_at = timestamp

    def _worker_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                event = self.event_queue.get(timeout=1.0)
            except Empty:
                continue
            try:
                self._process_file_event(event)
            except Exception:
                log.exception("File event error: %s", event.path)
            finally:
                self.event_queue.task_done()

    def _process_file_event(self, event: FileEvent) -> None:
        file_path = event.path
        if not file_path.exists() or not is_image_file(file_path):
            return

        normalized = normalize_path(file_path)
        with self.lock:
            if normalized in self.inflight_files:
                return
            self.inflight_files.add(normalized)

        try:
            parts = parse_satellite_country_folder(file_path.parent.name)
            if not parts:
                return
            satellite, country = parts

            with SessionLocal() as db:
                existing = load_existing_target_paths(db)
                if normalized in existing:
                    return

                parts = parse_satellite_country_folder(file_path.parent.name)
                if not parts:
                    return
                satellite, country = parts

                audit = FolderProcessingAudit(
                    input_file_path=normalized,
                    folder_name=file_path.parent.name,
                    satellite=satellite,
                    country=country,
                    detected_at=event.detected_at,
                    status="processing",
                    processing_started_at=_utcnow(),
                )
                db.add(audit)
                db.flush()

                job, error = process_new_target_file(db, file_path, existing, satellite)
                audit.processing_ended_at = _utcnow()
                if job is None:
                    audit.status = "failed"
                    audit.error_message = error or "processing_failed"
                else:
                    audit.job_id = job.id
                    audit.status = "completed" if job.status == "completed" else job.status
                    audit.error_message = job.error_message
                    audit.output_path = job.cloud_optimized_output_path or job.coregistered_output_path
                db.commit()
        finally:
            with self.lock:
                self.inflight_files.discard(normalized)
