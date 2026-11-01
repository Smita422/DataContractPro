"""Quarantined records inspection and diagnostic endpoints."""

import json
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from schemaguard.api.dependencies import get_storage
from schemaguard.api.schemas import (
    QuarantineDetailResponse,
    QuarantineItem,
    QuarantineListResponse,
)
from schemaguard.core.storage import DuckDBStorageManager
from schemaguard.utils.logger import logger

router = APIRouter(prefix="/quarantine", tags=["Quarantine"])


@router.get(
    "",
    response_model=QuarantineListResponse,
    summary="List Quarantined Records",
    description="Retrieve paginated list of quarantined record violations with filtering by dataset, batch, run, or violation type.",
)
def list_quarantine_records(
    limit: int = Query(default=50, ge=1, le=500, description="Maximum number of items to return"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
    dataset: Optional[str] = Query(default=None, description="Filter by dataset name"),
    batch_id: Optional[str] = Query(default=None, description="Filter by batch ID"),
    run_id: Optional[str] = Query(default=None, description="Filter by run ID"),
    violation_rule: Optional[str] = Query(default=None, description="Filter by violation rule or type keyword"),
    storage: DuckDBStorageManager = Depends(get_storage),
):
    """List quarantined records with pagination and filters."""
    where_clauses = []
    params: List[Any] = []

    if dataset:
        where_clauses.append("dataset_name = ?")
        params.append(dataset)

    if batch_id:
        where_clauses.append("batch_id = ?")
        params.append(batch_id)

    if run_id:
        where_clauses.append("run_id = ?")
        params.append(run_id)

    if violation_rule:
        where_clauses.append("violation_rule LIKE ?")
        params.append(f"%{violation_rule}%")

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    # Total count query
    count_sql = f"SELECT COUNT(*) FROM quarantined_records {where_sql}"
    total_count = storage.fetch_one(count_sql, params)[0] if params else storage.fetch_one(count_sql)[0]

    # Data query
    data_sql = f"""
    SELECT
        quarantine_id, run_id, batch_id, dataset_name, row_index,
        source_record_id, violation_field, violation_rule, error_message,
        source_file, quarantined_at
    FROM quarantined_records
    {where_sql}
    ORDER BY quarantined_at DESC
    LIMIT ? OFFSET ?
    """
    query_params = list(params) + [limit, offset]
    rows = storage.fetch_all(data_sql, query_params)

    items = [
        QuarantineItem(
            quarantine_id=r[0],
            run_id=r[1],
            batch_id=r[2],
            dataset_name=r[3],
            row_index=r[4],
            source_record_id=r[5],
            violation_field=r[6],
            violation_rule=r[7],
            error_message=r[8],
            source_file=r[9],
            quarantined_at=r[10],
        )
        for r in rows
    ]

    return QuarantineListResponse(
        items=items,
        total=total_count,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{record_id}",
    response_model=QuarantineDetailResponse,
    summary="Get Quarantined Record by ID",
    description="Retrieve complete violation diagnostic report and original raw JSON payload by quarantine_id or source record identifier.",
)
def get_quarantine_record_by_id(
    record_id: str,
    storage: DuckDBStorageManager = Depends(get_storage),
):
    """Retrieve full quarantine details including parsed raw record payload."""
    sql = """
    SELECT
        quarantine_id, run_id, batch_id, dataset_name, row_index,
        source_record_id, raw_record, violation_field, violation_rule,
        error_message, source_file, quarantined_at
    FROM quarantined_records
    WHERE quarantine_id = ? OR source_record_id = ?
    LIMIT 1
    """
    row = storage.fetch_one(sql, [record_id, record_id])
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Quarantined record '{record_id}' not found.",
        )

    # Parse raw JSON record
    raw_json_str = row[6]
    try:
        raw_payload = json.loads(raw_json_str) if raw_json_str else {}
    except Exception as exc:
        logger.warning(f"Failed to parse raw_record JSON for quarantine_id={row[0]}: {exc}")
        raw_payload = {"_raw": raw_json_str}

    return QuarantineDetailResponse(
        quarantine_id=row[0],
        run_id=row[1],
        batch_id=row[2],
        dataset_name=row[3],
        row_index=row[4],
        source_record_id=row[5],
        raw_record=raw_payload,
        violation_field=row[7],
        violation_rule=row[8],
        error_message=row[9],
        source_file=row[10],
        quarantined_at=row[11],
    )
