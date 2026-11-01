"""Health check endpoint for SchemaGuard API."""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from schemaguard.api.dependencies import get_storage
from schemaguard.api.schemas import HealthResponse
from schemaguard.core.storage import DuckDBStorageManager
from schemaguard.utils.logger import logger

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service Health Check",
    description="Returns application health status and validates DuckDB database connectivity.",
)
def get_health(storage: DuckDBStorageManager = Depends(get_storage)):
    """Check application and database health."""
    try:
        res = storage.fetch_one("SELECT 1")
        if res and res[0] == 1:
            db_status = "connected"
        else:
            db_status = "degraded"
    except Exception as exc:
        logger.error(f"Health check database ping failed: {exc}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "degraded",
                "database": "disconnected",
                "version": "0.1.0",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    return HealthResponse(
        status="healthy",
        database=db_status,
        version="0.1.0",
        timestamp=datetime.now(timezone.utc),
    )
