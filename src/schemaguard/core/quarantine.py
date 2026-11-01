"""Quarantine management for isolating, formatting, and storing invalid records."""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid
import pandas as pd
from pydantic import BaseModel, Field

from schemaguard.utils.logger import logger


class QuarantineRecord(BaseModel):
    """Encapsulates full diagnostic context for a rejected data record."""

    quarantine_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    batch_id: str
    dataset_name: str
    row_index: int
    source_record_id: Optional[str] = None
    raw_record: str
    violation_field: str
    violation_rule: str
    error_message: str
    source_file: str
    quarantined_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        """Convert record to dictionary for database insertion."""
        return {
            "quarantine_id": self.quarantine_id,
            "run_id": self.run_id,
            "batch_id": self.batch_id,
            "dataset_name": self.dataset_name,
            "row_index": self.row_index,
            "source_record_id": self.source_record_id,
            "raw_record": self.raw_record,
            "violation_field": self.violation_field,
            "violation_rule": self.violation_rule,
            "error_message": self.error_message,
            "source_file": self.source_file,
            "quarantined_at": self.quarantined_at,
        }


class QuarantineManager:
    """Manages the lifecycle, formatting, and file export of quarantined records."""

    @classmethod
    def create_record(
        cls,
        run_id: str,
        batch_id: str,
        dataset_name: str,
        row_index: int,
        raw_row: Dict[str, Any],
        violation_field: str,
        violation_rule: str,
        error_message: str,
        source_file: str,
        primary_key_field: Optional[str] = None,
    ) -> QuarantineRecord:
        """Construct a QuarantineRecord from row data and violation details."""
        # Clean internal metadata keys from raw record representation
        clean_raw = {
            k: v
            for k, v in raw_row.items()
            if not k.startswith("_source_") and not k.startswith("_sg_")
        }
        source_record_id = None
        if primary_key_field and primary_key_field in clean_raw:
            val = clean_raw[primary_key_field]
            if val is not None and str(val).strip():
                source_record_id = str(val).strip()

        return QuarantineRecord(
            run_id=run_id,
            batch_id=batch_id,
            dataset_name=dataset_name,
            row_index=row_index,
            source_record_id=source_record_id,
            raw_record=json.dumps(clean_raw, default=str),
            violation_field=violation_field,
            violation_rule=violation_rule,
            error_message=error_message,
            source_file=source_file,
        )

    @classmethod
    def export_to_file(
        cls,
        records: List[QuarantineRecord],
        output_dir: Path | str = "data/quarantine",
    ) -> Optional[Path]:
        """Optionally dump quarantined records to a JSON file for inspection."""
        if not records:
            return None

        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        sample = records[0]
        file_name = f"quarantine_{sample.dataset_name}_{sample.batch_id}_{sample.run_id}.json"
        target_file = out_path / file_name

        data = [r.to_dict() for r in records]
        with open(target_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

        logger.debug(f"Exported {len(records)} quarantine records to {target_file}")
        return target_file
