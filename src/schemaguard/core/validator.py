"""Vectorized and rule-based data quality validation engine."""

from collections import defaultdict
from datetime import datetime
import re
from typing import Any, Dict, List, Optional, Set
import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from schemaguard.core.contract import ColumnDefinition, Contract
from schemaguard.core.quarantine import QuarantineManager, QuarantineRecord
from schemaguard.core.storage import DuckDBStorageManager
from schemaguard.utils.logger import logger


class ValidationResult(BaseModel):
    """Encapsulates the outcome of data contract validation on a batch."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    dataset_name: str
    input_count: int
    valid_count: int
    rejected_count: int
    quarantine_records: List[QuarantineRecord]


class DataValidator:
    """Validates raw DataFrame batches against Data Contract specifications."""

    @classmethod
    def validate(
        cls,
        raw_df: pd.DataFrame,
        contract: Contract,
        batch_id: str,
        run_id: str,
        source_file: str,
        storage: Optional[DuckDBStorageManager] = None,
    ) -> tuple[pd.DataFrame, ValidationResult]:
        """Execute all structural, semantic, relational, and business rule validations."""
        input_count = len(raw_df)
        if input_count == 0:
            return raw_df.copy(), ValidationResult(
                dataset_name=contract.dataset,
                input_count=0,
                valid_count=0,
                rejected_count=0,
                quarantine_records=[],
            )

        # Dictionary mapping dataframe index -> List[QuarantineRecord]
        errors_by_index: Dict[int, List[QuarantineRecord]] = defaultdict(list)
        pk_field = contract.get_primary_key()

        # On-demand row dictionary cache to avoid costly row-by-row DataFrame conversions
        row_dict_cache: Dict[int, Dict[str, Any]] = {}

        def get_row_dict(idx: int) -> Dict[str, Any]:
            if idx not in row_dict_cache:
                row_dict_cache[idx] = raw_df.loc[idx].to_dict()
            return row_dict_cache[idx]

        # Helper to add quarantine errors
        def add_error(
            idx: int,
            field: str,
            rule: str,
            reason: str,
            raw_row: Optional[Dict[str, Any]] = None,
        ) -> None:
            if raw_row is None:
                raw_row = get_row_dict(idx)
            rec = QuarantineManager.create_record(
                run_id=run_id,
                batch_id=batch_id,
                dataset_name=contract.dataset,
                row_index=int(raw_row.get("_source_record_index", idx)),
                raw_row=raw_row,
                violation_field=field,
                violation_rule=rule,
                error_message=reason,
                source_file=source_file,
                primary_key_field=pk_field,
            )
            errors_by_index[idx].append(rec)

        # 1. Intra-batch Primary Key Uniqueness (Vectorized)
        if pk_field and pk_field in raw_df.columns:
            pk_series = raw_df[pk_field].astype(str).str.strip()
            dup_mask = (pk_series != "") & pk_series.duplicated(keep=False)
            for idx in raw_df[dup_mask].index:
                add_error(
                    idx=idx,
                    field=pk_field,
                    rule="primary_key_unique",
                    reason=f"Duplicate primary key '{raw_df.at[idx, pk_field]}' found in input batch.",
                )

        # 2. Intra-batch Unique Field Constraints (Vectorized)
        for col in contract.columns:
            if col.unique and col.name in raw_df.columns:
                series = raw_df[col.name].astype(str).str.strip().str.lower()
                dup_mask = (series != "") & series.duplicated(keep=False)
                for idx in raw_df[dup_mask].index:
                    add_error(
                        idx=idx,
                        field=col.name,
                        rule="unique",
                        reason=f"Duplicate value '{raw_df.at[idx, col.name]}' for unique field '{col.name}' found in batch.",
                    )

        # 3. Foreign Key Integrity Check (Vectorized)
        if contract.dataset == "orders" and "customer_id" in raw_df.columns:
            if storage is not None:
                try:
                    rows = storage.fetch_all("SELECT customer_id FROM published_customers")
                    existing_customers = {str(r[0]).strip() for r in rows}
                except Exception as exc:
                    logger.warning(f"Could not verify foreign keys against published_customers: {exc}")
                    existing_customers = None

                if existing_customers is not None:
                    cid_series = raw_df["customer_id"].astype(str).str.strip()
                    missing_or_empty_mask = (cid_series == "") | (~cid_series.isin(existing_customers))
                    for idx in raw_df[missing_or_empty_mask].index:
                        cid = str(raw_df.at[idx, "customer_id"]).strip()
                        if not cid:
                            reason = "Null or empty customer_id does not reference a valid customer in published_customers."
                        else:
                            reason = f"Referenced customer_id '{cid}' does not exist in published_customers."
                        add_error(
                            idx=idx,
                            field="customer_id",
                            rule="foreign_key: published_customers",
                            reason=reason,
                        )

        # 4. Column-Level Rule Validations
        for col in contract.columns:
            col_name = col.name
            if col_name not in raw_df.columns:
                continue

            # Pre-compile column constraint rules outside row iteration
            compiled_pattern = None
            if col.constraints and col.constraints.pattern:
                try:
                    compiled_pattern = re.compile(col.constraints.pattern)
                except Exception as err:
                    logger.error(f"Failed to compile pattern '{col.constraints.pattern}': {err}")

            allowed_set = None
            allowed_upper_set = None
            if col.constraints and col.constraints.allowed_values:
                allowed_set = set(col.constraints.allowed_values)
                allowed_upper_set = {str(a).upper() for a in allowed_set}

            col_min = col.constraints.min if col.constraints else None
            col_max = col.constraints.max if col.constraints else None

            # Iterate over column series values
            for idx, raw_val in raw_df[col_name].items():
                str_val = "" if raw_val is None or pd.isna(raw_val) else str(raw_val).strip()

                # A. Nullability check
                if not col.nullable and str_val == "":
                    add_error(
                        idx=idx,
                        field=col_name,
                        rule="not_null",
                        reason=f"Field '{col_name}' is required and cannot be null or empty.",
                    )
                    continue

                # If value is empty and nullable, skip further value-level checks
                if col.nullable and str_val == "":
                    continue

                # B. Data Type & Parseability checks
                parsed_num: Optional[float] = None
                if col.type == "integer":
                    try:
                        val_float = float(str_val)
                        if not val_float.is_integer():
                            raise ValueError("Not an integer")
                        parsed_num = val_float
                    except (ValueError, TypeError):
                        add_error(
                            idx=idx,
                            field=col_name,
                            rule="type: integer",
                            reason=f"Value '{str_val}' in column '{col_name}' cannot be parsed as an integer.",
                        )
                        continue

                elif col.type == "float":
                    try:
                        parsed_num = float(str_val)
                    except (ValueError, TypeError):
                        add_error(
                            idx=idx,
                            field=col_name,
                            rule="type: float",
                            reason=f"Value '{str_val}' in column '{col_name}' cannot be parsed as a float.",
                        )
                        continue

                elif col.type in ("timestamp", "date"):
                    try:
                        parsed_ts = datetime.fromisoformat(str_val)
                        if parsed_ts.year < 1900 or parsed_ts.year > 2100:
                            raise ValueError(f"Year {parsed_ts.year} out of valid range")
                    except Exception:
                        try:
                            parsed_ts = pd.to_datetime(str_val, errors="raise")
                            if parsed_ts.year < 1900 or parsed_ts.year > 2100:
                                raise ValueError(f"Year {parsed_ts.year} out of valid range")
                        except Exception:
                            add_error(
                                idx=idx,
                                field=col_name,
                                rule=f"type: {col.type}",
                                reason=f"Value '{str_val}' in column '{col_name}' is not a valid timestamp or date.",
                            )
                            continue

                # C. Regex Pattern check
                if compiled_pattern is not None:
                    if not compiled_pattern.match(str_val):
                        add_error(
                            idx=idx,
                            field=col_name,
                            rule=f"pattern: {col.constraints.pattern}",
                            reason=f"Value '{str_val}' does not match required pattern '{col.constraints.pattern}'.",
                        )

                # D. Allowed Values (Enum) check
                if allowed_upper_set is not None:
                    if str_val.upper() not in allowed_upper_set:
                        add_error(
                            idx=idx,
                            field=col_name,
                            rule="allowed_values",
                            reason=f"Value '{str_val}' not in allowed values: {sorted(allowed_set)}.",
                        )

                # E. Numeric Boundaries (Min / Max)
                if parsed_num is not None:
                    if col_min is not None and parsed_num < col_min:
                        add_error(
                            idx=idx,
                            field=col_name,
                            rule=f"min: {col_min}",
                            reason=f"Value {parsed_num} is less than minimum permitted {col_min}.",
                        )
                    if col_max is not None and parsed_num > col_max:
                        add_error(
                            idx=idx,
                            field=col_name,
                            rule=f"max: {col_max}",
                            reason=f"Value {parsed_num} exceeds maximum permitted {col_max}.",
                        )

        # 5. Split into Valid vs Quarantined Records
        rejected_indices = set(errors_by_index.keys())
        valid_indices = [idx for idx in raw_df.index if idx not in rejected_indices]

        valid_df = raw_df.loc[valid_indices].copy()

        # Flatten all quarantine records
        all_quarantine_records: List[QuarantineRecord] = []
        for records_list in errors_by_index.values():
            all_quarantine_records.extend(records_list)

        logger.info(
            f"Validation complete for '{contract.dataset}': {len(valid_df)} valid, "
            f"{len(rejected_indices)} rejected ({len(all_quarantine_records)} total violation items)."
        )

        result = ValidationResult(
            dataset_name=contract.dataset,
            input_count=input_count,
            valid_count=len(valid_df),
            rejected_count=len(rejected_indices),
            quarantine_records=all_quarantine_records,
        )

        return valid_df, result
