"""Pipeline execution history and run detail endpoints."""

from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from schemaguard.api.dependencies import get_storage
from schemaguard.api.schemas import (
    EvolutionChangeSchema,
    PipelineRunSummary,
    RunDetailResponse,
    RunsListResponse,
)
from schemaguard.core.storage import DuckDBStorageManager
from schemaguard.utils.logger import logger

router = APIRouter(prefix="/runs", tags=["Runs"])


@router.get(
    "",
    response_model=RunsListResponse,
    summary="List Pipeline Runs",
    description="Retrieve paginated history of pipeline execution attempts with optional filtering by dataset and status.",
)
def list_runs(
    limit: int = Query(default=50, ge=1, le=500, description="Maximum number of items to return"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
    dataset: Optional[str] = Query(default=None, description="Filter by dataset name"),
    run_status: Optional[str] = Query(default=None, alias="status", description="Filter by status (SUCCESS, PARTIAL_SUCCESS, SCHEMA_REJECTED, FAILED)"),
    storage: DuckDBStorageManager = Depends(get_storage),
):
    """List recent pipeline execution runs with pagination and filters."""
    where_clauses = []
    params: List[Any] = []

    if dataset:
        where_clauses.append("dataset_name = ?")
        params.append(dataset)

    if run_status:
        where_clauses.append("status = ?")
        params.append(run_status.upper())

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    # Total count query
    count_sql = f"SELECT COUNT(*) FROM pipeline_runs {where_sql}"
    total_count = storage.fetch_one(count_sql, params)[0] if params else storage.fetch_one(count_sql)[0]

    # Data query
    data_sql = f"""
    SELECT
        run_id, batch_id, batch_fingerprint, dataset_name, contract_version,
        status, total_records, valid_records, quarantined_records,
        published_records, updated_records, reconciliation_diff,
        start_time, end_time, duration_ms, source_file, error_summary, created_at
    FROM pipeline_runs
    {where_sql}
    ORDER BY created_at DESC
    LIMIT ? OFFSET ?
    """
    query_params = list(params) + [limit, offset]
    rows = storage.fetch_all(data_sql, query_params)

    items = []
    for r in rows:
        pub = r[9] or 0
        upd = r[10] or 0
        ins = max(0, pub - upd)
        items.append(
            PipelineRunSummary(
                run_id=r[0],
                batch_id=r[1],
                batch_fingerprint=r[2],
                dataset_name=r[3],
                contract_version=r[4],
                status=r[5],
                total_records=r[6] or 0,
                valid_records=r[7] or 0,
                quarantined_records=r[8] or 0,
                published_records=pub,
                inserted_records=ins,
                updated_records=upd,
                reconciliation_diff=r[11] or 0,
                start_time=r[12],
                end_time=r[13],
                duration_ms=r[14] or 0,
                source_file=r[15],
                error_summary=r[16],
                created_at=r[17],
            )
        )

    return RunsListResponse(
        items=items,
        total=total_count,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{run_id}",
    response_model=RunDetailResponse,
    summary="Get Pipeline Run by ID",
    description="Retrieve complete metadata, record metrics, and schema evolution events for a single run.",
)
def get_run_by_id(
    run_id: str,
    storage: DuckDBStorageManager = Depends(get_storage),
):
    """Retrieve full execution report for a specific pipeline run."""
    sql = """
    SELECT
        run_id, batch_id, batch_fingerprint, dataset_name, contract_version,
        status, total_records, valid_records, quarantined_records,
        published_records, updated_records, reconciliation_diff,
        start_time, end_time, duration_ms, source_file, error_summary, created_at
    FROM pipeline_runs
    WHERE run_id = ?
    """
    row = storage.fetch_one(sql, [run_id])
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline run '{run_id}' not found.",
        )

    pub = row[9] or 0
    upd = row[10] or 0
    ins = max(0, pub - upd)

    # Fetch any schema evolution events recorded for this run
    events_sql = """
    SELECT column_name, change_type, is_breaking, diff_details
    FROM schema_evolution_events
    WHERE run_id = ?
    ORDER BY detected_at ASC
    """
    event_rows = storage.fetch_all(events_sql, [run_id])
    schema_events = [
        EvolutionChangeSchema(
            column_name=er[0],
            change_type=er[1],
            impact="BREAKING" if er[2] else "NON_BREAKING",
            explanation=er[3] or "",
        )
        for er in event_rows
    ]

    return RunDetailResponse(
        run_id=row[0],
        batch_id=row[1],
        batch_fingerprint=row[2],
        dataset_name=row[3],
        contract_version=row[4],
        status=row[5],
        total_records=row[6] or 0,
        valid_records=row[7] or 0,
        quarantined_records=row[8] or 0,
        published_records=pub,
        inserted_records=ins,
        updated_records=upd,
        reconciliation_diff=row[11] or 0,
        start_time=row[12],
        end_time=row[13],
        duration_ms=row[14] or 0,
        source_file=row[15],
        error_summary=row[16],
        created_at=row[17],
        schema_evolution_events=schema_events,
    )
