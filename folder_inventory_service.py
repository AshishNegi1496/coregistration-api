"""Folder inventory service for change detection.

This module provides CRUD operations and change detection logic
for the FolderInventory model.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import FolderInventory
from utils import calculate_folder_size


def get_folder_inventory(db: Session, folder_name: str) -> Optional[FolderInventory]:
    """Get folder inventory record by name.
    
    Args:
        db: Database session.
        folder_name: Name of the folder to look up.
        
    Returns:
        FolderInventory record if found, None otherwise.
    """
    return db.scalar(select(FolderInventory).where(FolderInventory.folder_name == folder_name))


def create_folder_inventory(
    db: Session,
    folder_name: str,
    folder_size_bytes: int,
    modified_time: datetime,
) -> FolderInventory:
    """Create a new folder inventory record.
    
    Args:
        db: Database session.
        folder_name: Name of the folder.
        folder_size_bytes: Total size of folder contents in bytes.
        modified_time: Last modification timestamp of the folder.
        
    Returns:
        The created FolderInventory record.
    """
    inventory = FolderInventory(
        folder_name=folder_name,
        folder_size_bytes=folder_size_bytes,
        modified_time=modified_time,
       
        last_scanned_at=datetime.now(timezone.utc),
    )
    db.add(inventory)
    return inventory


def update_folder_inventory(
    db: Session,
    inventory: FolderInventory,
    folder_size_bytes: int,
    modified_time: datetime,
) -> FolderInventory:
    """Update an existing folder inventory record.
    
    Args:
        db: Database session.
        inventory: The inventory record to update.
        folder_size_bytes: New total size of folder contents in bytes.
        modified_time: New last modification timestamp of the folder.
        
    Returns:
        The updated FolderInventory record.
    """
    inventory.folder_size_bytes = folder_size_bytes
    inventory.modified_time = modified_time
    inventory.last_scanned_at = datetime.now(timezone.utc)
    return inventory


def get_or_create_inventory(db: Session, folder_path: Path) -> FolderInventory:
    """Get existing inventory or create new one for a folder.
    
    Args:
        db: Database session.
        folder_path: Path to the folder.
        
    Returns:
        Existing or newly created FolderInventory record.
    """
    folder_name = folder_path.name
    inventory = get_folder_inventory(db, folder_name)
    
    if inventory is None:
        # Get current folder metadata
        folder_size = calculate_folder_size(folder_path)
        try:
            modified_time = datetime.fromtimestamp(
                folder_path.stat().st_mtime, tz=timezone.utc
            )
        except (OSError, PermissionError):
            modified_time = datetime.now(timezone.utc)
        
        inventory = create_folder_inventory(
            db=db,
            folder_name=folder_name,
            folder_size_bytes=folder_size,
            modified_time=modified_time,
        )
    
    return inventory


def has_folder_changed(
    db: Session,
    folder_path: Path,
) -> tuple[bool, Optional[FolderInventory]]:
    """Check if a folder has changed since last scan.
    
    Compares current folder size and modification time against
    stored inventory values.
    
    Args:
        db: Database session.
        folder_path: Path to the folder to check.
        
    Returns:
        Tuple of (has_changed, inventory_record).
        - has_changed: True if folder should be processed.
        - inventory_record: The FolderInventory record (existing or new).
    """
    folder_name = folder_path.name
    
    # Get current folder metadata
    try:
        current_size = calculate_folder_size(folder_path)
        current_modified = datetime.fromtimestamp(
            folder_path.stat().st_mtime, tz=timezone.utc
        )
    except (OSError, PermissionError):
        # If we can't access the folder, skip processing
        return False, None
    
    inventory = get_folder_inventory(db, folder_name)
    
    if inventory is None:
        # First time seeing this folder - create record and process
        inventory = create_folder_inventory(
            db=db,
            folder_name=folder_name,
            folder_size_bytes=current_size,
            modified_time=current_modified,
        )
        return True, inventory
    
    # Check if folder is disabled
    if not inventory.enabled:
        return False, inventory
    
    # Check for changes in size or modification time
    size_changed = current_size != inventory.folder_size_bytes
    time_changed = (
        inventory.modified_time is None 
        or current_modified != inventory.modified_time
    )
    
    if size_changed or time_changed:
        # Update inventory with new values
        update_folder_inventory(
            db=db,
            inventory=inventory,
            folder_size_bytes=current_size,
            modified_time=current_modified,
        )
        return True, inventory
    
    # No changes detected - skip processing
    return False, inventory


def sync_all_folders(db: Session, root_path: Path) -> list[FolderInventory]:
    """Sync inventory records for all subfolders at startup.
    
    Creates inventory records for any folders that don't exist
    in the database yet. This ensures auto-initialization on
    scheduler startup.
    
    Args:
        db: Database session.
        root_path: Root path containing folders to sync.
        
    Returns:
        List of all FolderInventory records for the root's subfolders.
    """
    inventories = []
    
    if not root_path.exists():
        return inventories
    
    for folder in root_path.iterdir():
        if folder.is_dir():
            # This will create inventory if it doesn't exist
            inventory = get_or_create_inventory(db, folder)
            inventories.append(inventory)
    
    return inventories
