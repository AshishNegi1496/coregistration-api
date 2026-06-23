from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from db import SessionLocal
from models import SchedulerConfig

log = logging.getLogger("api.scheduler_config")
DEFAULT_INTERVAL_MINUTES = 60


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_default_scheduler_config() -> None:
    with SessionLocal() as db:
        if db.scalar(select(SchedulerConfig.id).limit(1)) is not None:
            return
        now = utcnow()
        db.add(SchedulerConfig(
            folder_path=str(settings.target_root),
            scan_interval_minutes=DEFAULT_INTERVAL_MINUTES,
            enabled=True,
            last_scan_at=now,
        ))
        db.commit()
        log.info("Created default scheduler config (%s min interval)", DEFAULT_INTERVAL_MINUTES)


def list_scheduler_configs(db: Session) -> list[SchedulerConfig]:
    ensure_default_scheduler_config()
    return list(db.scalars(select(SchedulerConfig)))


def primary_config(configs: list[SchedulerConfig]) -> SchedulerConfig | None:
    for config in configs:
        if Path(config.folder_path).resolve() == settings.target_root.resolve():
            return config
    return configs[0] if configs else None


def scan_is_due(config: SchedulerConfig, now: datetime) -> bool:
    if not config.enabled or config.last_scan_at is None:
        return False
    elapsed = (now - config.last_scan_at).total_seconds()
    return elapsed >= config.scan_interval_minutes * 60


def seconds_until_scan(config: SchedulerConfig, now: datetime) -> float:
    if config.last_scan_at is None:
        return float(config.scan_interval_minutes * 60)
    return max(0.0, config.scan_interval_minutes * 60 - (now - config.last_scan_at).total_seconds())


def reset_scan_timer(db: Session, configs: list[SchedulerConfig], now: datetime | None = None) -> None:
    now = now or utcnow()
    for config in configs:
        config.last_scan_at = now
        config.updated_at = now
