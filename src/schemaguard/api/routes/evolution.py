"""Schema Evolution Events API endpoints."""

from typing import Any, List, Optional
from fastapi import APIRouter, Depends, Query

from schemaguard.api.dependencies import get_storage
from schemaguard.api.schemas import (
    EvolutionEventItem,
    EvolutionEventsListResponse,
)
from schemaguard.core.storage import DuckDBStorageManager

router = APIRouter(prefix="/evolution", tags=["Evolution"])


@router.get(
    "/events",
    response_model=EvolutionEventsListResponse,
    summary="List Schema Evolution Events",
    description="Retrieve paginated history of schema drift and evolution events with optional filtering.",
)
def list_evolution_events(
    limit: int = Query(default=50, ge=1, le=500, description="Maximum number of items to return"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
    dataset: Optional[str] = Query(default=None, description="Filter by dataset name"),
    is_breaking: Optional[bool] = Query(default=None, description="Filter by breaking impact flag"),
    change_type: Optional[str] = Query(default=None, description="Filter by change type"),
    storage: DuckDBStorageManager = Depends(get_storage),
):
    """List schema evolution events across all pipeline executions."""
    where_clauses = []
    params: List[Any] = []

    if dataset:
        where_clauses.append("dataset_name = ?")
        params.append(dataset)

    if is_breaking is not None:
        where_clauses.append("is_breaking = ?")
        params.append(is_breaking)

    if change_type:
        where_clauses.append("change_type = ?")
        params.append(change_type.upper())

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    # Total count query
    count_sql = f"SELECT COUNT(*) FROM schema_evolution_events {where_sql}"
    total_count = (
        storage.fetch_one(count_sql, params)[0] if params else storage.fetch_one(count_sql)[0]
    )

    # Data query
    data_sql = f"""
    SELECT
        event_id, run_id, batch_id, dataset_name, contract_version,
        change_type, is_breaking, column_name, diff_details, detected_at
    FROM schema_evolution_events
    {where_sql}
    ORDER BY detected_at DESC
    LIMIT ? OFFSET ?
    """
    query_params = list(params) + [limit, offset]
    rows = storage.fetch_all(data_sql, query_params)

    items = [
        EvolutionEventItem(
            event_id=r[0],
            run_id=r[1],
            batch_id=r[2],
            dataset_name=r[3],
            contract_version=r[4],
            change_type=r[5],
            is_breaking=bool(r[6]),
            impact="BREAKING" if r[6] else "NON_BREAKING",
            column_name=r[7],
            diff_details=r[8],
            detected_at=r[9],
        )
        for r in rows
    ]

    return EvolutionEventsListResponse(
        items=items,
        total=total_count,
        limit=limit,
        offset=offset,
    )
