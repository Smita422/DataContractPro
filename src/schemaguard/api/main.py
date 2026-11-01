"""Main FastAPI application entry point for SchemaGuard."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from schemaguard.api.dependencies import get_storage
from schemaguard.api.routes import contracts, evolution, health, metrics, pipeline, quarantine, runs
from schemaguard.utils.logger import logger

API_VERSION = "0.1.0"
API_TITLE = "SchemaGuard Data Contract & Schema Evolution API"
API_DESCRIPTION = """
**SchemaGuard** is an enterprise data contract validation, schema evolution analysis, 
and pipeline orchestration platform.

### Capabilities:
- **Contract Management:** Discover datasets and inspect version-controlled YAML contract rules.
- **Pipeline Orchestration:** Ingest CSV datasets, validate contracts, compute derived fields, and publish idempotently.
- **Schema Evolution:** Detect non-breaking vs breaking schema changes in real time.
- **Quarantine Engine:** Isolate malformed records with fine-grained violation diagnostic rules.
- **Metrics & Observability:** Monitor live operational throughput and data quality statistics from DuckDB.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown lifecycle events."""
    logger.info("Initializing SchemaGuard FastAPI service...")
    try:
        storage = get_storage()
        storage._init_database()
        logger.info(f"SchemaGuard DuckDB initialized successfully at {storage.db_path}")
    except Exception as exc:
        logger.error(f"Failed to initialize database during startup: {exc}")

    yield

    logger.info("Shutting down SchemaGuard FastAPI service...")


app = FastAPI(
    title=API_TITLE,
    description=API_DESCRIPTION,
    version=API_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Enable CORS for browser access and Streamlit dashboards
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API v1 route modules
API_V1_PREFIX = "/api/v1"
app.include_router(health.router, prefix=API_V1_PREFIX)
app.include_router(contracts.router, prefix=API_V1_PREFIX)
app.include_router(pipeline.router, prefix=API_V1_PREFIX)
app.include_router(runs.router, prefix=API_V1_PREFIX)
app.include_router(evolution.router, prefix=API_V1_PREFIX)
app.include_router(quarantine.router, prefix=API_V1_PREFIX)
app.include_router(metrics.router, prefix=API_V1_PREFIX)


@app.get("/", tags=["Root"], summary="API Root", description="Returns API status and links to documentation.")
def root():
    """Root endpoint returning service identity and documentation links."""
    return {
        "service": "SchemaGuard API",
        "version": API_VERSION,
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "health_check": f"{API_V1_PREFIX}/health",
    }


# Standardized error handlers avoiding stack trace leaks
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle request validation errors cleanly without exposing internals."""
    errors = exc.errors()
    error_messages = []
    for err in errors:
        loc = " -> ".join([str(x) for x in err.get("loc", [])])
        msg = err.get("msg", "Validation error")
        error_messages.append(f"{loc}: {msg}")
    
    formatted_msg = "; ".join(error_messages)
    logger.warning(f"Request validation failure on {request.method} {request.url.path}: {formatted_msg}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": f"Request validation failed: {formatted_msg}"},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle standard HTTPExceptions cleanly."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all unhandled exception handler that prevents stack trace leaks."""
    logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred. Please contact the system administrator."},
    )
