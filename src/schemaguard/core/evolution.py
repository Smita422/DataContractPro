"""Schema Evolution Analyzer and Breaking vs Non-Breaking Compatibility Engine."""

from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Set
import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from schemaguard.core.contract import (
    ColumnDefinition,
    ConstraintRules,
    Contract,
)
from schemaguard.utils.logger import logger


class EvolutionClassification(str, Enum):
    """Classification of schema modifications."""
    BREAKING = "BREAKING"
    NON_BREAKING = "NON_BREAKING"


class ChangeType(str, Enum):
    """Granular classification of detected schema changes."""
    COLUMN_ADDED = "COLUMN_ADDED"
    COLUMN_REMOVED = "COLUMN_REMOVED"
    COLUMN_RENAMED = "COLUMN_RENAMED"
    UNEXPECTED_COLUMN = "UNEXPECTED_COLUMN"
    TYPE_CHANGED = "TYPE_CHANGED"
    NULLABILITY_CHANGED = "NULLABILITY_CHANGED"
    ALLOWED_VALUES_CHANGED = "ALLOWED_VALUES_CHANGED"
    CONSTRAINT_CHANGED = "CONSTRAINT_CHANGED"
    PRIMARY_KEY_CHANGED = "PRIMARY_KEY_CHANGED"


class EvolutionChange(BaseModel):
    """Detailed structural difference detected for a single column."""

    column_name: str
    change_type: ChangeType
    old_definition: Optional[Any] = None
    new_definition: Optional[Any] = None
    classification: EvolutionClassification
    explanation: str


class EvolutionReport(BaseModel):
    """Complete summary and audit report of a schema evolution analysis."""

    dataset_name: str
    base_version: Optional[str] = None
    target_version: Optional[str] = None
    mode: Literal["STRICT", "PERMISSIVE"] = "PERMISSIVE"
    changes: List[EvolutionChange] = Field(default_factory=list)
    is_breaking: bool = False
    compatibility_status: Literal["COMPATIBLE", "BREAKING", "IDENTICAL"] = "IDENTICAL"
    summary: str = ""

    def add_change(self, change: EvolutionChange) -> None:
        """Add a detected change and update overall breaking status."""
        self.changes.append(change)
        if change.classification == EvolutionClassification.BREAKING:
            self.is_breaking = True
            self.compatibility_status = "BREAKING"
        elif not self.is_breaking:
            self.compatibility_status = "COMPATIBLE"


# Compatible type widening map (Source -> Target allowed widenings)
SAFE_TYPE_WIDENINGS: Dict[str, Set[str]] = {
    "integer": {"float"},
    "date": {"timestamp"},
}


def _is_safe_widening(old_type: str, new_type: str) -> bool:
    """Determine if changing from old_type to new_type is a safe widening."""
    return new_type in SAFE_TYPE_WIDENINGS.get(old_type, set())


def _map_pandas_dtype_to_contract_type(dtype: Any) -> str:
    """Map Pandas/NumPy dtypes to SchemaGuard contract types."""
    dtype_str = str(dtype).lower()
    if "int" in dtype_str:
        return "integer"
    if "float" in dtype_str or "double" in dtype_str:
        return "float"
    if "bool" in dtype_str:
        return "boolean"
    if "datetime" in dtype_str or "timestamp" in dtype_str:
        return "timestamp"
    if "date" in dtype_str:
        return "date"
    return "string"


class SchemaEvolutionAnalyzer:
    """Analyzes differences between contracts or incoming data against contracts.

    Classifies every change as BREAKING or NON_BREAKING and provides actionable explanations
    detailing the impact on downstream consumers.
    """

    @classmethod
    def compare_contracts(
        cls,
        base_contract: Contract,
        target_contract: Contract,
        renamed_columns: Optional[Dict[str, str]] = None,
        mode: Literal["STRICT", "PERMISSIVE"] = "PERMISSIVE",
    ) -> EvolutionReport:
        """Compare two versioned contracts and classify all structural changes."""
        renames = renamed_columns or {}
        report = EvolutionReport(
            dataset_name=base_contract.dataset,
            base_version=base_contract.version,
            target_version=target_contract.version,
            mode=mode,
        )

        old_cols = {c.name: c for c in base_contract.columns}
        new_cols = {c.name: c for c in target_contract.columns}

        # 1. Check for renamed columns
        for old_name, new_name in renames.items():
            if old_name in old_cols and new_name in new_cols:
                report.add_change(
                    EvolutionChange(
                        column_name=new_name,
                        change_type=ChangeType.COLUMN_RENAMED,
                        old_definition=old_name,
                        new_definition=new_name,
                        classification=EvolutionClassification.BREAKING,
                        explanation=(
                            f"Column '{old_name}' was renamed to '{new_name}'. Downstream queries, "
                            f"views, or pipelines selecting '{old_name}' will fail."
                        ),
                    )
                )

        # 2. Check for removed columns
        for old_name, old_col in old_cols.items():
            if old_name in renames:
                continue  # Handled in renames
            if old_name not in new_cols:
                report.add_change(
                    EvolutionChange(
                        column_name=old_name,
                        change_type=ChangeType.COLUMN_REMOVED,
                        old_definition=old_col.model_dump(),
                        new_definition=None,
                        classification=EvolutionClassification.BREAKING,
                        explanation=(
                            f"Column '{old_name}' was removed. Downstream transformations, dashboards, "
                            f"and consumer jobs expecting this field will encounter missing column errors."
                        ),
                    )
                )

        # 3. Check for added columns
        for new_name, new_col in new_cols.items():
            if new_name in renames.values():
                continue  # Handled in renames
            if new_name not in old_cols:
                if not new_col.nullable and new_col.default is None:
                    report.add_change(
                        EvolutionChange(
                            column_name=new_name,
                            change_type=ChangeType.COLUMN_ADDED,
                            old_definition=None,
                            new_definition=new_col.model_dump(),
                            classification=EvolutionClassification.BREAKING,
                            explanation=(
                                f"Mandatory non-nullable column '{new_name}' added without a default value. "
                                f"Producers or historical datasets cannot fulfill this requirement without failure."
                            ),
                        )
                    )
                else:
                    report.add_change(
                        EvolutionChange(
                            column_name=new_name,
                            change_type=ChangeType.COLUMN_ADDED,
                            old_definition=None,
                            new_definition=new_col.model_dump(),
                            classification=EvolutionClassification.NON_BREAKING,
                            explanation=(
                                f"Optional column '{new_name}' added. Downstream consumers can consume "
                                f"it or safely ignore it."
                            ),
                        )
                    )

        # 4. Check modified existing columns
        common_columns = set(old_cols.keys()).intersection(set(new_cols.keys()))
        for col_name in common_columns:
            old_col = old_cols[col_name]
            new_col = new_cols[col_name]
            cls._compare_column_definitions(old_col, new_col, report)

        cls._finalize_summary(report)
        return report

    @classmethod
    def compare_batch_to_contract(
        cls,
        df: pd.DataFrame,
        contract: Contract,
        mode: Literal["STRICT", "PERMISSIVE"] = "PERMISSIVE",
    ) -> EvolutionReport:
        """Compare an incoming producer DataFrame against the active Contract schema.

        Detects missing required columns, unexpected columns (handled per STRICT/PERMISSIVE mode),
        and data type mismatches.
        """
        report = EvolutionReport(
            dataset_name=contract.dataset,
            target_version=contract.version,
            mode=mode,
        )

        contract_cols = {c.name: c for c in contract.columns}
        df_col_names = list(df.columns)

        # 1. Missing columns in batch that are defined in the contract
        for name, col in contract_cols.items():
            if name not in df_col_names:
                if not col.nullable:
                    report.add_change(
                        EvolutionChange(
                            column_name=name,
                            change_type=ChangeType.COLUMN_REMOVED,
                            old_definition=col.model_dump(),
                            new_definition=None,
                            classification=EvolutionClassification.BREAKING,
                            explanation=(
                                f"Required column '{name}' is missing from incoming producer batch. "
                                f"Downstream pipeline requires this field."
                            ),
                        )
                    )
                else:
                    report.add_change(
                        EvolutionChange(
                            column_name=name,
                            change_type=ChangeType.COLUMN_REMOVED,
                            old_definition=col.model_dump(),
                            new_definition=None,
                            classification=EvolutionClassification.NON_BREAKING,
                            explanation=(
                                f"Optional column '{name}' is omitted from incoming batch. "
                                f"Default/null will be assigned."
                            ),
                        )
                    )

        # 2. Unexpected columns in batch
        for name in df_col_names:
            if name.startswith("_"):
                continue  # Skip internal lineage and record tracking metadata
            if name not in contract_cols:
                inferred_type = _map_pandas_dtype_to_contract_type(df[name].dtype)
                if mode == "STRICT":
                    report.add_change(
                        EvolutionChange(
                            column_name=name,
                            change_type=ChangeType.UNEXPECTED_COLUMN,
                            old_definition=None,
                            new_definition={"name": name, "inferred_type": inferred_type},
                            classification=EvolutionClassification.BREAKING,
                            explanation=(
                                f"Unexpected column '{name}' found under STRICT mode. "
                                f"Producers must not include unregistered columns."
                            ),
                        )
                    )
                else:
                    report.add_change(
                        EvolutionChange(
                            column_name=name,
                            change_type=ChangeType.UNEXPECTED_COLUMN,
                            old_definition=None,
                            new_definition={"name": name, "inferred_type": inferred_type},
                            classification=EvolutionClassification.NON_BREAKING,
                            explanation=(
                                f"Unexpected column '{name}' found under PERMISSIVE mode. "
                                f"Column will be recorded and ignored or ingested safely."
                            ),
                        )
                    )

        # 3. Check data types for matching columns (if batch is not empty)
        if not df.empty:
            for name in df_col_names:
                if name in contract_cols:
                    col = contract_cols[name]
                    inferred_type = _map_pandas_dtype_to_contract_type(df[name].dtype)
                    if col.type != inferred_type:
                        # Raw text batches (e.g. CSV with object/string dtype) are transport-serialized text.
                        # Cell-level parseability is validated per-row by DataValidator.
                        if inferred_type == "string":
                            continue

                        # Check for float representation of integers (pandas nullable ints)
                        if col.type == "integer" and inferred_type == "float":
                            non_nulls = df[name].dropna()
                            if non_nulls.empty or (non_nulls == non_nulls.round()).all():
                                continue  # Pure integers stored in float column

                        if _is_safe_widening(col.type, inferred_type) or _is_safe_widening(
                            inferred_type, col.type
                        ):
                            report.add_change(
                                EvolutionChange(
                                    column_name=name,
                                    change_type=ChangeType.TYPE_CHANGED,
                                    old_definition=col.type,
                                    new_definition=inferred_type,
                                    classification=EvolutionClassification.NON_BREAKING,
                                    explanation=(
                                        f"Safe numeric/temporal widening detected for '{name}': "
                                        f"'{col.type}' to '{inferred_type}'."
                                    ),
                                )
                            )
                        else:
                            report.add_change(
                                EvolutionChange(
                                    column_name=name,
                                    change_type=ChangeType.TYPE_CHANGED,
                                    old_definition=col.type,
                                    new_definition=inferred_type,
                                    classification=EvolutionClassification.BREAKING,
                                    explanation=(
                                        f"Incompatible type mismatch for '{name}': contract expects "
                                        f"'{col.type}', batch contains '{inferred_type}'."
                                    ),
                                )
                            )

        cls._finalize_summary(report)
        return report

    @classmethod
    def _compare_column_definitions(
        cls, old_col: ColumnDefinition, new_col: ColumnDefinition, report: EvolutionReport
    ) -> None:
        """Compare properties of an existing column across contract versions."""
        col_name = old_col.name

        # 1. Primary Key change
        if old_col.primary_key != new_col.primary_key:
            report.add_change(
                EvolutionChange(
                    column_name=col_name,
                    change_type=ChangeType.PRIMARY_KEY_CHANGED,
                    old_definition=f"primary_key={old_col.primary_key}",
                    new_definition=f"primary_key={new_col.primary_key}",
                    classification=EvolutionClassification.BREAKING,
                    explanation=(
                        f"Primary key definition changed for '{col_name}'. Modifying primary keys "
                        f"disrupts entity deduplication and foreign key relationships."
                    ),
                )
            )

        # 2. Type change
        if old_col.type != new_col.type:
            if _is_safe_widening(old_col.type, new_col.type):
                report.add_change(
                    EvolutionChange(
                        column_name=col_name,
                        change_type=ChangeType.TYPE_CHANGED,
                        old_definition=old_col.type,
                        new_definition=new_col.type,
                        classification=EvolutionClassification.NON_BREAKING,
                        explanation=(
                            f"Type widened from '{old_col.type}' to '{new_col.type}'. "
                            f"Safe conversion without truncation."
                        ),
                    )
                )
            else:
                report.add_change(
                    EvolutionChange(
                        column_name=col_name,
                        change_type=ChangeType.TYPE_CHANGED,
                        old_definition=old_col.type,
                        new_definition=new_col.type,
                        classification=EvolutionClassification.BREAKING,
                        explanation=(
                            f"Incompatible type change from '{old_col.type}' to '{new_col.type}'. "
                            f"Downstream parsers and storage types will fail."
                        ),
                    )
                )

        # 3. Nullability change
        if old_col.nullable != new_col.nullable:
            if not old_col.nullable and new_col.nullable:
                report.add_change(
                    EvolutionChange(
                        column_name=col_name,
                        change_type=ChangeType.NULLABILITY_CHANGED,
                        old_definition="nullable=False",
                        new_definition="nullable=True",
                        classification=EvolutionClassification.NON_BREAKING,
                        explanation=(
                            f"Nullability for '{col_name}' relaxed from NOT NULL to NULLABLE. "
                            f"Consumers will not break."
                        ),
                    )
                )
            else:
                report.add_change(
                    EvolutionChange(
                        column_name=col_name,
                        change_type=ChangeType.NULLABILITY_CHANGED,
                        old_definition="nullable=True",
                        new_definition="nullable=False",
                        classification=EvolutionClassification.BREAKING,
                        explanation=(
                            f"Nullability for '{col_name}' tightened from NULLABLE to NOT NULL. "
                            f"Incoming records with null values will be rejected."
                        ),
                    )
                )

        # 4. Constraints comparison
        old_c = old_col.constraints or ConstraintRules()
        new_c = new_col.constraints or ConstraintRules()

        # Allowed values (Enums)
        if old_c.allowed_values or new_c.allowed_values:
            old_set = set(old_c.allowed_values) if old_c.allowed_values else set()
            new_set = set(new_c.allowed_values) if new_c.allowed_values else set()
            if old_set != new_set:
                removed_vals = old_set - new_set
                added_vals = new_set - old_set
                if removed_vals:
                    report.add_change(
                        EvolutionChange(
                            column_name=col_name,
                            change_type=ChangeType.ALLOWED_VALUES_CHANGED,
                            old_definition=sorted(old_set),
                            new_definition=sorted(new_set),
                            classification=EvolutionClassification.BREAKING,
                            explanation=(
                                f"Allowed enum values restricted for '{col_name}'. Removed: {sorted(removed_vals)}. "
                                f"Producers sending removed values will now fail."
                            ),
                        )
                    )
                elif added_vals:
                    report.add_change(
                        EvolutionChange(
                            column_name=col_name,
                            change_type=ChangeType.ALLOWED_VALUES_CHANGED,
                            old_definition=sorted(old_set),
                            new_definition=sorted(new_set),
                            classification=EvolutionClassification.NON_BREAKING,
                            explanation=(
                                f"Allowed enum values expanded for '{col_name}'. Added: {sorted(added_vals)}. "
                                f"Existing values remain fully valid."
                            ),
                        )
                    )

        # Numeric / length boundaries
        # Min
        if old_c.min is not None or new_c.min is not None:
            if old_c.min is not None and new_c.min is not None:
                if new_c.min > old_c.min:
                    report.add_change(
                        EvolutionChange(
                            column_name=col_name,
                            change_type=ChangeType.CONSTRAINT_CHANGED,
                            old_definition=f"min={old_c.min}",
                            new_definition=f"min={new_c.min}",
                            classification=EvolutionClassification.BREAKING,
                            explanation=(
                                f"Minimum value for '{col_name}' restricted from {old_c.min} to {new_c.min}."
                            ),
                        )
                    )
                elif new_c.min < old_c.min:
                    report.add_change(
                        EvolutionChange(
                            column_name=col_name,
                            change_type=ChangeType.CONSTRAINT_CHANGED,
                            old_definition=f"min={old_c.min}",
                            new_definition=f"min={new_c.min}",
                            classification=EvolutionClassification.NON_BREAKING,
                            explanation=(
                                f"Minimum value for '{col_name}' relaxed from {old_c.min} to {new_c.min}."
                            ),
                        )
                    )

        # Max
        if old_c.max is not None or new_c.max is not None:
            if old_c.max is not None and new_c.max is not None:
                if new_c.max < old_c.max:
                    report.add_change(
                        EvolutionChange(
                            column_name=col_name,
                            change_type=ChangeType.CONSTRAINT_CHANGED,
                            old_definition=f"max={old_c.max}",
                            new_definition=f"max={new_c.max}",
                            classification=EvolutionClassification.BREAKING,
                            explanation=(
                                f"Maximum value for '{col_name}' restricted from {old_c.max} to {new_c.max}."
                            ),
                        )
                    )
                elif new_c.max > old_c.max:
                    report.add_change(
                        EvolutionChange(
                            column_name=col_name,
                            change_type=ChangeType.CONSTRAINT_CHANGED,
                            old_definition=f"max={old_c.max}",
                            new_definition=f"max={new_c.max}",
                            classification=EvolutionClassification.NON_BREAKING,
                            explanation=(
                                f"Maximum value for '{col_name}' relaxed from {old_c.max} to {new_c.max}."
                            ),
                        )
                    )

    @staticmethod
    def _finalize_summary(report: EvolutionReport) -> None:
        """Formulate a concise human-readable summary of the evolution report."""
        if not report.changes:
            report.compatibility_status = "IDENTICAL"
            report.summary = f"No schema changes detected for dataset '{report.dataset_name}'."
            return

        breaking_count = sum(
            1 for c in report.changes if c.classification == EvolutionClassification.BREAKING
        )
        non_breaking_count = len(report.changes) - breaking_count

        if breaking_count > 0:
            report.compatibility_status = "BREAKING"
            report.summary = (
                f"BREAKING EVOLUTION: {breaking_count} breaking change(s) and "
                f"{non_breaking_count} non-breaking change(s) detected for '{report.dataset_name}'."
            )
        else:
            report.compatibility_status = "COMPATIBLE"
            report.summary = (
                f"NON-BREAKING EVOLUTION: {non_breaking_count} compatible change(s) "
                f"detected for '{report.dataset_name}'."
            )
