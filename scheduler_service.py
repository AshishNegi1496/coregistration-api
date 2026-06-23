from __future__ import annotations

import logging
import threading
from pathlib import Path

from config import settings
from db import SessionLocal
from services.job_service import load_existing_target_paths
from services.scheduler_config import ensure_default_scheduler_config, list_scheduler_configs, scan_is_due, seconds_until_scan, utcnow
from services.target_processing import process_new_target_file
from utils import list_image_files

log = logging.getLogger("api.scheduler")


def run_scheduled_scan(*, force: bool = False) -> dict:
    now = utcnow()
    scanned_folders: list[str] = []
    new_files: list[str] = []
    jobs_started: list[int] = []
    skipped: list[str] = []

    with SessionLocal() as db:
        configs = list_scheduler_configs(db)
        existing_targets = load_existing_target_paths(db)

        for config in configs:
            root_folder = Path(config.folder_path)
            if root_folder.resolve() != settings.target_root.resolve():
                continue
            if not root_folder.is_dir():
                continue

            if not force and not scan_is_due(config, now):
                skipped.append(f"{config.folder_path} ({seconds_until_scan(config, now):.0f}s remaining)")
                continue

            scanned_folders.append(str(root_folder))
            for img_path in list_image_files(root_folder, recursive=True):
                job, _error = process_new_target_file(db, img_path, existing_targets)
                if job is None:
                    continue
                new_files.append(str(img_path))
                jobs_started.append(job.job_number)

            config.last_scan_at = now

        db.commit()

    return {
        "status": "ok",
        "scanned_folders": scanned_folders,
        "new_files_found": new_files,
        "jobs_started": jobs_started,
        "skipped": skipped,
        "message": f"Found {len(new_files)} new file(s), started {len(jobs_started)} job(s)",
    }


class SchedulerService:
    def __init__(self, poll_interval_seconds: float = 30.0) -> None:
        self.poll_interval_seconds = poll_interval_seconds
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        ensure_default_scheduler_config()
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True, name="scheduler-service")
        self.thread.start()
        log.info("Scheduler service started (poll every %ss)", self.poll_interval_seconds)

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=10)
            self.thread = None

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                result = run_scheduled_scan(force=False)
                if result["scanned_folders"]:
                    log.info("Scheduled scan: %d job(s) started", len(result["jobs_started"]))
            except Exception:
                log.exception("Scheduler loop error")
            self.stop_event.wait(self.poll_interval_seconds)
