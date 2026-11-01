"""Operational and data quality metrics endpoints."""

from fastapi import APIRouter, Depends

from schemaguard.api.dependencies import get_storage
from schemaguard.api.schemas import DatasetMetrics, MetricsSummaryResponse
from schemaguard.core.storage import DuckDBStorageManager

router = APIRouter(prefix="/metrics", tags=["Metrics"])


@router.get(
    "/summary",
    response_model=MetricsSummaryResponse,
    summary="Data Quality and Pipeline Metrics Summary",
    description="Calculate live operational and data quality metrics aggregated directly from DuckDB run history.",
)
def get_metrics_summary(storage: DuckDBStorageManager = Depends(get_storage)):
    """Aggregate total runs, published counts, quarantine rates, and per-dataset statistics."""
    overall_sql = """
    SELECT
        COUNT(*) AS total_runs,
        COUNT(*) FILTER (WHERE status = 'SUCCESS') AS successful_runs,
        COUNT(*) FILTER (WHERE status = 'PARTIAL_SUCCESS') AS partial_success_runs,
        COUNT(*) FILTER (WHERE status = 'FAILED') AS failed_runs,
        COUNT(*) FILTER (WHERE status = 'SCHEMA_REJECTED') AS schema_rejected_runs,
        COALESCE(SUM(total_records), 0) AS total_input_records,
        COALESCE(SUM(published_records), 0) AS total_published_records,
        COALESCE(SUM(quarantined_records), 0) AS total_rejected_records
    FROM pipeline_runs
    """
    row = storage.fetch_one(overall_sql)
    if not row:
        row = (0, 0, 0, 0, 0, 0, 0, 0)

    dataset_sql = """
    SELECT
        dataset_name,
        COUNT(*) AS total_runs,
        COUNT(*) FILTER (WHERE status = 'SUCCESS') AS successful_runs,
        COUNT(*) FILTER (WHERE status = 'PARTIAL_SUCCESS') AS partial_success_runs,
        COUNT(*) FILTER (WHERE status = 'FAILED') AS failed_runs,
        COUNT(*) FILTER (WHERE status = 'SCHEMA_REJECTED') AS schema_rejected_runs,
        COALESCE(SUM(total_records), 0) AS total_input_records,
        COALESCE(SUM(published_records), 0) AS total_published_records,
        COALESCE(SUM(quarantined_records), 0) AS total_quarantined_records
    FROM pipeline_runs
    GROUP BY dataset_name
    ORDER BY dataset_name ASC
    """
    dataset_rows = storage.fetch_all(dataset_sql)
    dataset_metrics = [
        DatasetMetrics(
            dataset_name=dr[0],
            total_runs=dr[1],
            successful_runs=dr[2],
            partial_success_runs=dr[3],
            failed_runs=dr[4],
            schema_rejected_runs=dr[5],
            total_input_records=dr[6],
            total_published_records=dr[7],
            total_quarantined_records=dr[8],
        )
        for dr in dataset_rows
    ]

    return MetricsSummaryResponse(
        total_runs=row[0],
        successful_runs=row[1],
        partial_success_runs=row[2],
        failed_runs=row[3],
        schema_rejected_runs=row[4],
        total_input_records=row[5],
        total_published_records=row[6],
        total_rejected_records=row[7],
        datasets=dataset_metrics,
    )
