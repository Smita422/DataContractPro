"""Data ingestion module for reading raw producer batches and computing lineage metadata."""

import hashlib
from pathlib import Path
from typing import Optional
import uuid
import pandas as pd
from pydantic import BaseModel, ConfigDict

from schemaguard.utils.logger import logger


class IngestionError(Exception):
    """Base exception for ingestion failures."""
    pass


class EmptyFileError(IngestionError):
    """Raised when an ingested file has 0 bytes or no data rows."""
    pass


class MalformedFileError(IngestionError):
    """Raised when an input file cannot be parsed as a valid CSV."""
    pass


class IngestionPayload(BaseModel):
    """Encapsulates raw ingested data along with execution and lineage identifiers."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    dataset_name: str
    file_path: str
    source_filename: str
    batch_id: str
    run_id: str
    batch_fingerprint: str
    record_count: int


def compute_file_fingerprint(file_path: Path | str) -> str:
    """Compute deterministic SHA-256 fingerprint from file contents."""
    path = Path(file_path)
    sha256_hash = hashlib.sha256()
    with open(path, "rb") as f:
        for byte_block in iter(lambda: f.read(65536), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


class DataIngestor:
    """Handles raw file reading, lineage generation, and deterministic batch hashing."""

    @classmethod
    def read_csv(
        cls,
        file_path: Path | str,
        dataset_name: str,
        batch_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> tuple[pd.DataFrame, IngestionPayload]:
        """Read producer CSV file, preserving raw string values and computing fingerprints."""
        path = Path(file_path)
        if not path.is_file():
            raise IngestionError(f"File not found: {path}")

        # Check empty file (0 bytes)
        if path.stat().st_size == 0:
            raise EmptyFileError(f"Input file is completely empty (0 bytes): {path}")

        # Calculate deterministic file fingerprint
        fingerprint = compute_file_fingerprint(path)

        # Generate deterministic batch_id if not explicitly provided
        effective_batch_id = batch_id or f"batch_{dataset_name}_{fingerprint[:12]}"
        # Generate new unique run_id for this individual execution attempt
        effective_run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"

        try:
            # Read all columns as raw strings, preserving empty strings without silent NaN conversions
            df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
        except Exception as exc:
            raise MalformedFileError(f"Unable to parse CSV file {path}: {exc}") from exc

        if df.empty:
            raise EmptyFileError(f"Input CSV file contains no data records: {path}")

        # Add tracking metadata columns
        df["_source_record_index"] = range(len(df))
        df["_source_filename"] = path.name

        payload = IngestionPayload(
            dataset_name=dataset_name,
            file_path=str(path),
            source_filename=path.name,
            batch_id=effective_batch_id,
            run_id=effective_run_id,
            batch_fingerprint=fingerprint,
            record_count=len(df),
        )

        logger.info(
            f"Ingested {len(df)} records from {path.name} | Batch: {effective_batch_id} | Run: {effective_run_id}"
        )
        return df, payload
