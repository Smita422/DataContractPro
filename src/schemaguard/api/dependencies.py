"""FastAPI dependency injection and security validation utilities."""

import os
from pathlib import Path
import tempfile
from typing import Generator, List, Optional
from fastapi import Depends, HTTPException, status

from schemaguard.core.pipeline import PipelineOrchestrator
from schemaguard.core.storage import DuckDBStorageManager

# Module-level default storage manager for API runtime
_default_storage: Optional[DuckDBStorageManager] = None


def get_storage() -> DuckDBStorageManager:
    """Return the shared DuckDB storage manager instance.

    Can be overridden in tests using app.dependency_overrides[get_storage].
    """
    global _default_storage
    if _default_storage is None:
        _default_storage = DuckDBStorageManager()
    return _default_storage


def get_orchestrator(
    storage: DuckDBStorageManager = Depends(get_storage),
) -> PipelineOrchestrator:
    """Return a PipelineOrchestrator configured with the active storage manager."""
    return PipelineOrchestrator(storage=storage)


def get_allowed_base_dirs() -> List[Path]:
    """Return list of permitted base directories for file ingestion."""
    cwd = Path.cwd().resolve()
    temp_dir = Path(tempfile.gettempdir()).resolve()
    allowed = [cwd, temp_dir]
    
    # Also include pytest temporary path root if set
    basetemp = os.environ.get("PYTEST_BASE_TEMP")
    if basetemp:
        allowed.append(Path(basetemp).resolve())
        
    return allowed


def validate_file_path(file_path_str: str) -> Path:
    """Validate that the requested file path is safe and exists within allowed directories.

    Raises:
        HTTPException(400): If the path attempts directory traversal or points outside allowed directories.
        HTTPException(404): If the file does not exist on disk.
    """
    if not file_path_str or not file_path_str.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File path must not be empty.",
        )

    try:
        raw_path = Path(file_path_str.strip())
        resolved_path = raw_path.resolve()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file path syntax: {exc}",
        )

    # Restrict file processing to allowed directories (workspace or temp dirs)
    allowed_roots = get_allowed_base_dirs()
    is_allowed = any(
        resolved_path == root or root in resolved_path.parents for root in allowed_roots
    )

    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Access to the specified file path is restricted. "
                "Files must reside within the project workspace or temporary data directory."
            ),
        )

    if not resolved_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Input file not found at path: {file_path_str}",
        )

    return resolved_path
