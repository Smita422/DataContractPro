"""Core pipeline orchestrator coordinating ingestion, evolution, validation, and storage."""

from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any, Dict, List, Literal, Optional
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from schemaguard.core.contract import Contract, load_contract
from schemaguard.core.evolution import (
    EvolutionChange,
    EvolutionReport,
    SchemaEvolutionAnalyzer,
)
from schemaguard.core.ingestion import DataIngestor, EmptyFileError, IngestionError, IngestionPayload
from schemaguard.core.quarantine import QuarantineManager, QuarantineRecord
from schemaguard.core.reconciliation import ReconciliationEngine, ReconciliationReport
from schemaguard.core.storage import DuckDBStorageManager
from schemaguard.core.transformation import DataTransformer
from schemaguard.core.validator import DataValidator, ValidationResult
from schemaguard.utils.logger import logger


class PipelineExecutionResult(BaseModel):
    """Complete summary of a pipeline execution attempt."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_id: str
    batch_id: str
    batch_fingerprint: str
    dataset_name: str
    contract_version: Optional[str] = None
    status: Literal["SUCCESS", "PARTIAL_SUCCESS", "SCHEMA_REJECTED", "FAILED"]
    total_records: int = 0
    valid_records: int = 0
    quarantined_records: int = 0
    published_records: int = 0
    inserted_records: int = 0
    updated_records: int = 0
    reconciliation_diff: int = 0
    reconciliation_report: Optional[ReconciliationReport] = None
    duration_ms: int = 0
    source_file: str
    error_summary: Optional[str] = None
    schema_changes: List[EvolutionChange] = Field(default_factory=list)


class PipelineOrchestrator:
    """Orchestrates end-to-end data contract validation, evolution, and loading."""

    def __init__(
        self,
        storage: Optional[DuckDBStorageManager] = None,
        contracts_dir: Optional[Path | str] = None,
    ):
        self.storage = storage or DuckDBStorageManager()
        self.contracts_dir = Path(contracts_dir) if contracts_dir else None

    def run(
        self,
        file_path: Path | str,
        dataset_name: str,
        version: Optional[str] = None,
        mode: Literal["STRICT", "PERMISSIVE"] = "PERMISSIVE",
        batch_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> PipelineExecutionResult:
        """Execute the end-to-end ingestion and validation pipeline for a batch file."""
        start_time = datetime.now(timezone.utc)
        t0 = time.perf_counter()
        source_path = Path(file_path)

        # 1. Ingestion Phase
        try:
            raw_df, payload = DataIngestor.read_csv(
                file_path=source_path,
                dataset_name=dataset_name,
                batch_id=batch_id,
                run_id=run_id,
            )
        except Exception as exc:
            duration_ms = int((time.perf_counter() - t0) * 1000)
            err_msg = f"Ingestion error: {exc}"
            logger.error(err_msg)

            # Record failed run
            failed_run_id = run_id or f"run_err_{int(time.time())}"
            failed_batch_id = batch_id or f"batch_err_{source_path.stem}"
            run_record = {
                "run_id": failed_run_id,
                "batch_id": failed_batch_id,
                "batch_fingerprint": "",
                "dataset_name": dataset_name,
                "contract_version": version or "unknown",
                "status": "FAILED",
                "total_records": 0,
                "valid_records": 0,
                "quarantined_records": 0,
                "reconciliation_diff": 0,
                "start_time": start_time,
                "end_time": datetime.now(timezone.utc),
                "duration_ms": duration_ms,
                "source_file": source_path.name,
                "error_summary": err_msg,
            }
            self.storage.record_pipeline_run(run_record)
            return PipelineExecutionResult(
                run_id=failed_run_id,
                batch_id=failed_batch_id,
                batch_fingerprint="",
                dataset_name=dataset_name,
                contract_version=version,
                status="FAILED",
                source_file=source_path.name,
                duration_ms=duration_ms,
                error_summary=err_msg,
            )

        # 2. Contract Resolution
        try:
            contract = load_contract(
                dataset_name=dataset_name,
                version=version,
                contracts_dir=self.contracts_dir,
            )
        except Exception as exc:
            duration_ms = int((time.perf_counter() - t0) * 1000)
            err_msg = f"Contract resolution failure: {exc}"
            logger.error(err_msg)
            run_record = {
                "run_id": payload.run_id,
                "batch_id": payload.batch_id,
                "batch_fingerprint": payload.batch_fingerprint,
                "dataset_name": dataset_name,
                "contract_version": version or "unknown",
                "status": "FAILED",
                "total_records": len(raw_df),
                "valid_records": 0,
                "quarantined_records": 0,
                "reconciliation_diff": len(raw_df),
                "start_time": start_time,
                "end_time": datetime.now(timezone.utc),
                "duration_ms": duration_ms,
                "source_file": payload.source_filename,
                "error_summary": err_msg,
            }
            self.storage.record_pipeline_run(run_record)
            return PipelineExecutionResult(
                run_id=payload.run_id,
                batch_id=payload.batch_id,
                batch_fingerprint=payload.batch_fingerprint,
                dataset_name=dataset_name,
                contract_version=version,
                status="FAILED",
                total_records=len(raw_df),
                source_file=payload.source_filename,
                duration_ms=duration_ms,
                error_summary=err_msg,
            )

        # 3. Schema Compatibility & Evolution Check
        evolution_report = SchemaEvolutionAnalyzer.compare_batch_to_contract(
            df=raw_df, contract=contract, mode=mode
        )

        # Log any evolution changes into audit table
        for change in evolution_report.changes:
            self.storage.log_schema_evolution({
                "event_id": f"evt_{payload.run_id}_{change.column_name}",
                "run_id": payload.run_id,
                "batch_id": payload.batch_id,
                "dataset_name": dataset_name,
                "contract_version": contract.version,
                "change_type": change.change_type.value,
                "is_breaking": change.classification.value == "BREAKING",
                "column_name": change.column_name,
                "diff_details": change.explanation,
            })

        # Breaking schema change detected: Halt batch publication!
        if evolution_report.is_breaking:
            duration_ms = int((time.perf_counter() - t0) * 1000)
            logger.warning(
                f"Batch {payload.batch_id} rejected due to breaking schema evolution: "
                f"{evolution_report.summary}"
            )

            # Record rejected run with complete trace
            run_record = {
                "run_id": payload.run_id,
                "batch_id": payload.batch_id,
                "batch_fingerprint": payload.batch_fingerprint,
                "dataset_name": dataset_name,
                "contract_version": contract.version,
                "status": "SCHEMA_REJECTED",
                "total_records": len(raw_df),
                "valid_records": 0,
                "quarantined_records": len(raw_df),
                "reconciliation_diff": 0,
                "start_time": start_time,
                "end_time": datetime.now(timezone.utc),
                "duration_ms": duration_ms,
                "source_file": payload.source_filename,
                "error_summary": evolution_report.summary,
            }
            self.storage.record_pipeline_run(run_record)

            # Quarantine all records due to schema rejection
            pk_col = contract.get_primary_key()
            rejection_records = []
            for idx, row in raw_df.iterrows():
                rec = QuarantineManager.create_record(
                    run_id=payload.run_id,
                    batch_id=payload.batch_id,
                    dataset_name=dataset_name,
                    row_index=int(row.get("_source_record_index", idx)),
                    raw_row=row.to_dict(),
                    violation_field="schema",
                    violation_rule="schema_compatibility",
                    error_message=evolution_report.summary,
                    source_file=payload.source_filename,
                    primary_key_field=pk_col,
                )
                rejection_records.append(rec.to_dict())

            self.storage.insert_quarantine_records(rejection_records)

            return PipelineExecutionResult(
                run_id=payload.run_id,
                batch_id=payload.batch_id,
                batch_fingerprint=payload.batch_fingerprint,
                dataset_name=dataset_name,
                contract_version=contract.version,
                status="SCHEMA_REJECTED",
                total_records=len(raw_df),
                valid_records=0,
                quarantined_records=len(raw_df),
                published_records=0,
                reconciliation_diff=0,
                duration_ms=duration_ms,
                source_file=payload.source_filename,
                error_summary=evolution_report.summary,
                schema_changes=evolution_report.changes,
            )

        # 4. Record-Level Validation
        valid_df, val_result = DataValidator.validate(
            raw_df=raw_df,
            contract=contract,
            batch_id=payload.batch_id,
            run_id=payload.run_id,
            source_file=payload.source_filename,
            storage=self.storage,
        )

        # 5. Deterministic Transformation
        transformed_df = DataTransformer.transform(
            dataset_name=dataset_name,
            valid_df=valid_df,
            batch_id=payload.batch_id,
            run_id=payload.run_id,
            source_file=payload.source_filename,
        )

        # 6. Atomic DuckDB Publishing & Staging Upsert
        pk_col = contract.get_primary_key() or f"{dataset_name[:-1]}_id"
        upsert_stats = {"published_count": 0, "inserted_count": 0, "updated_count": 0}

        try:
            with self.storage.transaction() as tx_con:
                if not transformed_df.empty:
                    upsert_stats = self.storage.upsert_published_records(
                        table_name=dataset_name,
                        df=transformed_df,
                        primary_key=pk_col,
                        con=tx_con,
                        return_details=True,
                    )

                if val_result.quarantine_records:
                    quarantine_dicts = [r.to_dict() for r in val_result.quarantine_records]
                    self.storage.insert_quarantine_records(quarantine_dicts, con=tx_con)

        except Exception as exc:
            duration_ms = int((time.perf_counter() - t0) * 1000)
            err_msg = f"Database publish transaction failed and was rolled back: {exc}"
            logger.error(err_msg)
            run_record = {
                "run_id": payload.run_id,
                "batch_id": payload.batch_id,
                "batch_fingerprint": payload.batch_fingerprint,
                "dataset_name": dataset_name,
                "contract_version": contract.version,
                "status": "FAILED",
                "total_records": len(raw_df),
                "valid_records": 0,
                "quarantined_records": 0,
                "reconciliation_diff": len(raw_df),
                "start_time": start_time,
                "end_time": datetime.now(timezone.utc),
                "duration_ms": duration_ms,
                "source_file": payload.source_filename,
                "error_summary": err_msg,
            }
            self.storage.record_pipeline_run(run_record)
            raise

        # 7. Source-to-Target Reconciliation
        reconcile_report = ReconciliationEngine.reconcile(
            batch_id=payload.batch_id,
            run_id=payload.run_id,
            dataset_name=dataset_name,
            input_count=val_result.input_count,
            valid_count=val_result.valid_count,
            rejected_count=val_result.rejected_count,
            inserted_count=upsert_stats["inserted_count"],
            updated_count=upsert_stats["updated_count"],
        )

        # 8. Run Status and Audit History Recording
        status = "SUCCESS" if val_result.rejected_count == 0 else "PARTIAL_SUCCESS"
        duration_ms = int((time.perf_counter() - t0) * 1000)

        run_record = {
            "run_id": payload.run_id,
            "batch_id": payload.batch_id,
            "batch_fingerprint": payload.batch_fingerprint,
            "dataset_name": dataset_name,
            "contract_version": contract.version,
            "status": status,
            "total_records": val_result.input_count,
            "valid_records": val_result.valid_count,
            "quarantined_records": val_result.rejected_count,
            "published_records": upsert_stats["published_count"],
            "duplicate_records": upsert_stats["updated_count"],
            "updated_records": upsert_stats["updated_count"],
            "reconciliation_diff": reconcile_report.reconciliation_diff,
            "start_time": start_time,
            "end_time": datetime.now(timezone.utc),
            "duration_ms": duration_ms,
            "source_file": payload.source_filename,
            "error_summary": None if status == "SUCCESS" else f"{val_result.rejected_count} records quarantined",
        }
        self.storage.record_pipeline_run(run_record)

        return PipelineExecutionResult(
            run_id=payload.run_id,
            batch_id=payload.batch_id,
            batch_fingerprint=payload.batch_fingerprint,
            dataset_name=dataset_name,
            contract_version=contract.version,
            status=status,
            total_records=val_result.input_count,
            valid_records=val_result.valid_count,
            quarantined_records=val_result.rejected_count,
            published_records=upsert_stats["published_count"],
            inserted_records=upsert_stats["inserted_count"],
            updated_records=upsert_stats["updated_count"],
            reconciliation_diff=reconcile_report.reconciliation_diff,
            reconciliation_report=reconcile_report,
            duration_ms=duration_ms,
            source_file=payload.source_filename,
            error_summary=run_record["error_summary"],
            schema_changes=evolution_report.changes,
        )
