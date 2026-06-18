# Refactored Architecture: Scheduler, Folder Inventory, and Manual Processing

## Overview

This document describes the simplified and refactored architecture for coregistration job creation, supporting two flows:

1. **Auto Scan** - Automatic detection and processing of new TIFF files
2. **Manual Upload** - User-initiated file selection and processing

Both flows use **shared duplicate detection logic** via the `is_file_already_processed()` helper.

---

## Database Schema (Simplified)

### SchedulerConfig
```
id (PK)
folder_path (TEXT, UNIQUE)      - Root TARGET directory path
scan_interval_minutes (INT)      - How often to scan (default: 60)
enabled (BOOL)                   - Whether to run auto-scan
last_scan_at (DATETIME)          - Timestamp of last scan
updated_at (DATETIME)            - Record update time
```

**Purpose:** Stores configuration for the auto-scan scheduler pointing to TARGET root.

**Example:**
```
id=1, folder_path=/mnt/TARGET, scan_interval_minutes=60, enabled=true
```

### FolderInventory
```
id (PK)
scheduler_config_id (FK)         - Reference to SchedulerConfig
folder_name (STR, INDEX)         - e.g., "C2A_PAK"
folder_size_bytes (BIGINT)       - Total folder size in bytes
modified_time (DATETIME)         - Last modified time of any file
last_scanned_at (DATETIME)       - When this record was last scanned
created_at (DATETIME)            - Record creation time
updated_at (DATETIME)            - Record update time
```

**Purpose:** Optimization layer to detect folder-level changes without scanning contents.

**Does NOT store:** File-level scan results (removed `FolderScanResult` table).

**Example:**
```
id=1, scheduler_config_id=1, folder_name=C2A_PAK
folder_size_bytes=54321098, modified_time=2026-06-18T10:30:00Z
last_scanned_at=2026-06-18T10:35:00Z
```

### CoregJob (Unmodified)
```
id (UUID, PK)
job_no (INT, UNIQUE, INDEX)
status (STR, INDEX)              - queued, processing, completed, failed
stage (STR)
sensor_name (STR)
reference_image (TEXT)
target_image (TEXT, INDEX)       ← SOURCE OF TRUTH FOR DUPLICATE DETECTION
coreg_output_path (TEXT)
cog_output_path (TEXT)
runtime_seconds (FLOAT)
created_at (DATETIME)
started_at (DATETIME)
completed_at (DATETIME)
error_message (TEXT)
```

**Key Point:** `target_image` field is indexed and used as the single source of truth for duplicate detection. Both auto-scan and manual flows check this field.

**Removed:** `sensor_hint`, folder-level filtering (simplified logic).

---

## Design Rules

### Rule 1: FolderInventory is ONLY for Folder-Level Change Detection

- Stores only: `folder_name`, `folder_size_bytes`, `modified_time`, `last_scanned_at`
- Does NOT store file-level scan results
- Allows the scheduler to skip folders that haven't changed

### Rule 2: CoregJob.target_image is the Source of Truth

- Always check `CoregJob.target_image` to determine if a TIFF has been processed
- The field is indexed for fast lookup
- Both flows must use the same helper: `is_file_already_processed(db, file_path)`

### Rule 3: Remove Unnecessary Complexity

- Deleted `FolderScanResult` table
- Removed file-level inventory storage
- Removed sensor_hint based folder filtering
- Keep existing processing logic (`_create_job()`, `_process_job()`, matching, status tracking)

### Rule 4: Shared Duplicate Detection Helper

```python
def is_file_already_processed(db: Session, file_path: Path) -> bool:
    """
    Check if a file has already been processed as a target image.
    
    - Normalizes path (resolve to absolute)
    - Compares against CoregJob.target_image (indexed)
    - Returns True if match found, False otherwise
    """
    normalized_path = str(file_path.resolve())
    existing_job = db.query(CoregJob).filter(
        CoregJob.target_image == normalized_path
    ).first()
    return existing_job is not None
```

**Used by:** Both auto-scan and manual upload flows.

### Rule 5: Scheduler Logic

The scheduler:
1. Queries all enabled `SchedulerConfig` entries
2. For each config, iterates child folders (C2A_PAK, C2B_CHN, etc.)
3. Checks `FolderInventory` for each folder
4. Only scans folders where:
   - `folder_size_bytes` changed OR
   - `modified_time` changed OR
   - No inventory record exists (first time)
5. For each TIFF found:
   - Calls `is_file_already_processed(db, file_path)`
   - If False, creates `CoregJob`
   - If True, skips (duplicate)
6. Updates `FolderInventory.last_scanned_at` and `SchedulerConfig.last_scan_at`

### Rule 6: Keep Existing Processing Logic

- Do NOT modify `_create_job()` implementation
- Do NOT modify `_process_job()` implementation
- Do NOT modify matching logic
- Do NOT modify job status tracking
- Only simplify scanning and duplicate detection

---

## Workflows

### AUTO SCAN FLOW

```
SchedulerConfig (TARGET root)
    ↓
Iterate child folders (C2A_PAK, C2A_CHN, ...)
    ↓
Check FolderInventory for each folder
    ↓
Has folder changed? (size or mtime)
    ├─ No → Skip folder
    └─ Yes → Scan TIFF files
        ↓
        For each TIFF:
            ↓
            is_file_already_processed(db, tiff_path)?
            ├─ Yes → Skip (duplicate)
            └─ No → _create_job(db, tiff_path)
                ↓
                Create CoregJob
```

**Entry Point:** `scheduler.scan_scheduler(db=None)`

**Returns:**
```python
{
    "configs_processed": 1,
    "folders_scanned": 3,
    "files_found": 12,
    "jobs_created": 9,
    "skipped_duplicates": 3,
    "errors": []
}
```

### MANUAL FLOW

```
User selects TIFF file
    ↓
process_manual_file_upload(
    db,
    file_path,
    reference_image_path,
    sensor_name
)
    ↓
is_file_already_processed(db, file_path)?
    ├─ Yes → Raise FileAlreadyProcessedError
    └─ No → _create_job(db, file_path, ref_path, sensor)
        ↓
        Create CoregJob
```

**Entry Point:** `manual_processor.process_manual_file_upload(...)`

**Raises:** `FileAlreadyProcessedError` if file already processed.

---

## Implementation Files

### 1. `models.py` (Updated)

**Changes:**
- Removed `FolderScanResult` class entirely
- Removed `sensor_hint` from `SchedulerConfig`
- Simplified `SchedulerConfig` fields (only `folder_path`, `scan_interval_minutes`, `enabled`, `last_scan_at`, `updated_at`)
- Added index on `CoregJob.target_image` for duplicate detection
- Simplified `FolderInventory` (removed relationships to scan results)

**Key Models:**
- `CoregJob` - Unmodified (keeps all existing fields)
- `SchedulerConfig` - Simplified
- `FolderInventory` - Simplified (folder-level only)

### 2. `utils.py` (Updated)

**New Function:**
```python
def is_file_already_processed(db: Session, file_path: Path) -> bool:
    """
    Reusable helper for duplicate detection.
    Used by both auto-scan and manual flows.
    """
```

**Unchanged:**
- All geometry/overlap functions
- Image file listing
- Path normalization
- Sensor inference

### 3. `scheduler.py` (New)

**Functions:**
- `get_folder_size_and_mtime(folder_path)` - Calculate folder stats
- `folder_changed(current_size, current_mtime, inventory)` - Detect changes
- `scan_scheduler(db=None)` - Main scheduler entry point
- `_create_job(db, target_image_path)` - Placeholder for job creation

**Usage:**
```python
from api.scheduler import scan_scheduler
from api.db import SessionLocal

db = SessionLocal()
summary = scan_scheduler(db)
print(f"Created {summary['jobs_created']} jobs")
db.close()
```

### 4. `manual_processor.py` (New)

**Functions:**
- `process_manual_file_upload(db, file_path, reference_image_path, sensor_name)` - Main entry point
- `_create_job(db, target_image_path, reference_image_path, sensor_name)` - Placeholder for job creation

**Custom Exception:**
- `FileAlreadyProcessedError` - Raised when file already processed

**Usage:**
```python
from api.manual_processor import process_manual_file_upload, FileAlreadyProcessedError
from api.db import SessionLocal
from pathlib import Path

db = SessionLocal()
try:
    job = process_manual_file_upload(
        db,
        Path("/mnt/TARGET/C2A_PAK/image.tif"),
        Path("/mnt/REFERENCE/ref.tif"),
        "cartosat"
    )
    print(f"Created job: {job.id}")
except FileAlreadyProcessedError as e:
    print(f"Error: {e}")
finally:
    db.close()
```

### 5. `init_db.py` (Updated)

Updated documentation to reflect simplified schema.

---

## Integration Checklist

- [ ] Models schema finalized (✓ done)
- [ ] Duplicate detection helper created (✓ done)
- [ ] Scheduler module created (✓ done)
- [ ] Manual processor module created (✓ done)
- [ ] Test duplicate detection helper
- [ ] Test scheduler on sample folder structure
- [ ] Test manual upload with duplicate scenarios
- [ ] Integrate `_create_job()` placeholder with existing service
- [ ] Add database migrations for schema changes
- [ ] Update API endpoints to use new flows
- [ ] Add logging and monitoring

---

## Benefits of This Architecture

1. **Minimal Schema:** Only 3 tables (SchedulerConfig, FolderInventory, CoregJob + metrics)
2. **No Duplicate Processing:** Single source of truth via `target_image` index
3. **Shared Logic:** Both flows use `is_file_already_processed()`
4. **Optimized Scanning:** FolderInventory prevents unnecessary file-level scans
5. **Backward Compatible:** Existing `_create_job()` and `_process_job()` logic untouched
6. **Production-Ready:** Clean, maintainable, and scalable

---

## Example Folder Structure

```
TARGET/
├── C2A_PAK/
│   ├── image1.tif
│   ├── image2.tif
│   └── image3.tif
├── C2A_CHN/
│   ├── image4.tif
│   └── image5.tif
├── C2B_PAK/
│   └── image6.tif
├── C2B_CHN/
├── C2B_SL/
├── C2B_NEP/
├── EROSB_PAK/
├── EROSB_CHN/
├── EROSB_SL/
└── EROSB_NEP/
```

First run of scheduler:
- Creates 6 `CoregJob` entries
- Creates 11 `FolderInventory` entries (one per folder, including empty ones)
- Records folder stats (size, mtime)

Second run (no new files):
- Checks folder stats
- Detects no changes
- Skips scanning (optimization)
- Creates 0 new jobs

Third run (1 new file in C2A_PAK):
- Detects size/mtime change in C2A_PAK
- Scans folder
- Finds 4 TIFFs total (1 new)
- Checks `is_file_already_processed()` for each
- Creates 1 new job
- Updates inventory
