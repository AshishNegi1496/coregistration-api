from __future__ import annotations

from sqlalchemy.engine import Engine

from api.db import Base

# Import all models so SQLAlchemy registers them
from api.models import (
    CoregistrationJob,
    CoregistrationMetrics,
    CoregistrationParameters,
    CoregistrationPixelSize,
    SystemPerformanceMetrics,
    OverallStatistics,
    SchedulerConfig,
)


def ensure_schema(engine: Engine) -> None:
    """
    Create all tables defined in models.py.

    Since the schema was redesigned from:
        jobs -> coreg_job
        job_logs -> coreg_metrics

    the old ALTER TABLE migration logic is no longer valid.
    """

    Base.metadata.create_all(bind=engine)