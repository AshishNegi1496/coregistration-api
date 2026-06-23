"""
Database initialization with simplified schema.

Removed tables:
- FolderScanResult (file-level results)
- Sensor-hint based folder filtering

Remaining tables:
- CoregJob: Source of truth for processed files (via target_image index)
- FolderInventory: Folder-level change detection only
- SchedulerConfig: Scheduler configuration
- CoregMetrics, CoregParameter, CoregPixelSize, CoregSystemPerformance, CoregOverallStat
"""

from db import engine
from models import Base


def init_db():
    """Initialize database with all tables."""
    Base.metadata.create_all(bind=engine)
    print("Database initialized successfully")


if __name__ == "__main__":
    init_db()
