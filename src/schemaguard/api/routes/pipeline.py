"""Pipeline execution API endpoint."""

from fastapi import APIRouter, Depends, HTTPException, status

from schemaguard.api.dependencies import get_orchestrator, validate_file_path
from schemaguard.api.schemas import (
    EvolutionChangeSchema,
    PipelineRunRequest,
    PipelineRunResponse,
)
from schemaguard.core.contract import ContractNotFoundError, load_contract
from schemaguard.core.pipeline import PipelineOrchestrator
from schemaguard.utils.logger import logger

router = APIRouter(prefix="/pipeline", tags=["Pipeline"])


@router.post(
    "/runs",
    response_model=PipelineRunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Execute Pipeline Run",
    description="Ingest, validate against contract, detect schema evolution, quarantine invalid records, and publish valid data.",
)
def execute_pipeline_run(
    req: PipelineRunRequest,
    orchestrator: PipelineOrchestrator = Depends(get_orchestrator),
):
    """Trigger an end-to-end data contract validation pipeline execution."""
    # 1. Validate file path safety and existence
    resolved_file = validate_file_path(req.file_path)

    # 2. Validate that the dataset contract exists
    try:
        load_contract(dataset_name=req.dataset, version=req.contract_version)
    except ContractNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    # 3. Execute core pipeline
    logger.info(
        f"API triggering pipeline run for dataset='{req.dataset}', file='{resolved_file}', "
        f"mode='{req.schema_mode}', version='{req.contract_version}'"
    )

    try:
        result = orchestrator.run(
            file_path=resolved_file,
            dataset_name=req.dataset,
            version=req.contract_version,
            mode=req.schema_mode,
        )
    except Exception as exc:
        logger.error(f"Pipeline execution unhandled exception: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline execution failed: {exc}",
        )

    # 4. Map schema evolution changes
    evolution_changes = [
        EvolutionChangeSchema(
            column_name=ch.column_name,
            change_type=str(ch.change_type.value if hasattr(ch.change_type, "value") else ch.change_type),
            impact=str(ch.classification.value if hasattr(ch.classification, "value") else ch.classification),
            explanation=ch.explanation,
        )
        for ch in result.schema_changes
    ]

    reconcile_status = (
        "BALANCED (diff=0)"
        if result.reconciliation_diff == 0
        else f"UNBALANCED (diff={result.reconciliation_diff})"
    )

    return PipelineRunResponse(
        run_id=result.run_id,
        batch_id=result.batch_id,
        batch_fingerprint=result.batch_fingerprint,
        dataset=result.dataset_name,
        contract_version=result.contract_version,
        status=result.status,
        total_records=result.total_records,
        valid_records=result.valid_records,
        quarantined_records=result.quarantined_records,
        published_records=result.published_records,
        inserted_records=result.inserted_records,
        updated_records=result.updated_records,
        reconciliation_diff=result.reconciliation_diff,
        reconciliation_status=reconcile_status,
        duration_ms=result.duration_ms,
        source_file=result.source_file,
        error_summary=result.error_summary,
        schema_changes=evolution_changes,
    )
