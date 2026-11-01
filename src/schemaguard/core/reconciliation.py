"""Independent source-to-target reconciliation module for audit accounting."""

from pydantic import BaseModel, Field

from schemaguard.utils.logger import logger


class ReconciliationReport(BaseModel):
    """Encapsulates detailed accounting metrics comparing source input to target outputs."""

    batch_id: str
    run_id: str
    dataset_name: str
    input_count: int = 0
    valid_count: int = 0
    rejected_count: int = 0
    duplicate_count: int = 0
    published_count: int = 0
    inserted_count: int = 0
    updated_count: int = 0
    failed_count: int = 0
    reconciliation_diff: int = 0
    is_balanced: bool = True
    explanation: str = ""


class ReconciliationEngine:
    """Verifies pipeline accounting equations and formulates operational explanations."""

    @classmethod
    def reconcile(
        cls,
        batch_id: str,
        run_id: str,
        dataset_name: str,
        input_count: int,
        valid_count: int,
        rejected_count: int,
        inserted_count: int = 0,
        updated_count: int = 0,
        failed_count: int = 0,
    ) -> ReconciliationReport:
        """Calculate reconciliation metrics, verify core balance equation, and explain results."""
        # Fundamental equation: input_count must equal valid_count + rejected_count
        expected_total = valid_count + rejected_count
        reconciliation_diff = input_count - expected_total
        is_balanced = (reconciliation_diff == 0)

        # Published count is the total rows committed into target storage
        published_count = inserted_count + updated_count

        # Duplicate count represents valid records that already existed in the target table (updates)
        duplicate_count = updated_count

        # Formulate human-readable explanation
        explanation_lines = [
            f"Source Batch Summary for '{dataset_name}':",
            f"  - Received {input_count} raw input records.",
            f"  - {valid_count} records passed data contract validation.",
            f"  - {rejected_count} records failed validation and were quarantined.",
        ]

        if not is_balanced:
            explanation_lines.append(
                f"  - [ALERT] Reconciliation imbalance: diff={reconciliation_diff} "
                f"(input={input_count} vs accounted={expected_total})."
            )
        else:
            explanation_lines.append(
                "  - [BALANCED] Complete balance: input_count = valid_count + rejected_count."
            )

        explanation_lines.append(
            f"Target Storage Breakdown:\n"
            f"  - {published_count} valid records written to warehouse ({inserted_count} new inserts, "
            f"{updated_count} updates to existing records).\n"
            f"  - Note: published_count ({published_count}) may differ from valid_count ({valid_count}) "
            f"if intra-batch deduplication or partial storage failures occur."
        )

        full_explanation = "\n".join(explanation_lines)
        if not is_balanced:
            logger.warning(full_explanation)
        else:
            logger.info(f"Reconciliation verified successfully for {batch_id} (diff=0)")

        return ReconciliationReport(
            batch_id=batch_id,
            run_id=run_id,
            dataset_name=dataset_name,
            input_count=input_count,
            valid_count=valid_count,
            rejected_count=rejected_count,
            duplicate_count=duplicate_count,
            published_count=published_count,
            inserted_count=inserted_count,
            updated_count=updated_count,
            failed_count=failed_count,
            reconciliation_diff=reconciliation_diff,
            is_balanced=is_balanced,
            explanation=full_explanation,
        )
