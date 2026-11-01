"""Pydantic request and response schemas for SchemaGuard REST API."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# ==============================================================================
# Health Schemas
# ==============================================================================

class HealthResponse(BaseModel):
    """Health status response."""
    status: str = Field(..., description="Application health status (e.g. 'healthy')")
    database: str = Field(..., description="Database connection status ('connected' or 'disconnected')")
    version: str = Field(..., description="SchemaGuard API version")
    timestamp: datetime = Field(..., description="Current server UTC timestamp")


# ==============================================================================
# Contract Schemas
# ==============================================================================

class ContractsListResponse(BaseModel):
    """Listing of all available contracts and their versions."""
    datasets: Dict[str, List[str]] = Field(..., description="Mapping of dataset names to version lists")
    total_datasets: int = Field(..., description="Total number of registered datasets")


class ConstraintRulesSchema(BaseModel):
    """Constraint rules for a column."""
    min: Optional[float] = None
    max: Optional[float] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    pattern: Optional[str] = None
    allowed_values: Optional[List[str]] = None


class ColumnDefinitionSchema(BaseModel):
    """Column definition within a contract."""
    name: str
    type: str
    nullable: bool = False
    primary_key: bool = False
    unique: bool = False
    default: Optional[Any] = None
    description: Optional[str] = None
    constraints: Optional[ConstraintRulesSchema] = None


class DerivedFieldSchema(BaseModel):
    """Derived column specification."""
    name: str
    type: str
    expression: str
    description: Optional[str] = None


class ContractDetailResponse(BaseModel):
    """Detailed contract specification for a dataset."""
    dataset: str
    version: str
    owner: str
    domain: Optional[str] = None
    compatibility_mode: str
    description: Optional[str] = None
    columns: List[ColumnDefinitionSchema]
    derived_fields: List[DerivedFieldSchema] = Field(default_factory=list)


# ==============================================================================
# Pipeline Execution Schemas
# ==============================================================================

class PipelineRunRequest(BaseModel):
    """Request payload to execute the validation pipeline."""
    dataset: str = Field(..., min_length=1, description="Target dataset name (e.g. 'customers', 'orders')")
    file_path: str = Field(..., min_length=1, description="Path to the input CSV file")
    contract_version: Optional[str] = Field(default=None, description="Specific contract version or 'latest'")
    schema_mode: Literal["PERMISSIVE", "STRICT"] = Field(
        default="PERMISSIVE",
        description="Handling mode for unexpected columns ('PERMISSIVE' or 'STRICT')"
    )


class EvolutionChangeSchema(BaseModel):
    """Schema evolution change event description."""
    column_name: Optional[str] = None
    change_type: str
    impact: str
    explanation: str


class PipelineRunResponse(BaseModel):
    """Response returned upon pipeline execution."""
    run_id: str
    batch_id: str
    batch_fingerprint: str
    dataset: str
    contract_version: Optional[str] = None
    status: str = Field(..., description="Execution status: SUCCESS, PARTIAL_SUCCESS, SCHEMA_REJECTED, FAILED")
    total_records: int
    valid_records: int
    quarantined_records: int
    published_records: int
    inserted_records: int
    updated_records: int
    reconciliation_diff: int
    reconciliation_status: str
    duration_ms: int
    source_file: str
    error_summary: Optional[str] = None
    schema_changes: List[EvolutionChangeSchema] = Field(default_factory=list)


# ==============================================================================
# Run History Schemas
# ==============================================================================

class PipelineRunSummary(BaseModel):
    """Summary of a past pipeline run."""
    run_id: str
    batch_id: str
    batch_fingerprint: str
    dataset_name: str
    contract_version: Optional[str] = None
    status: str
    total_records: int
    valid_records: int
    quarantined_records: int
    published_records: int
    inserted_records: int
    updated_records: int
    reconciliation_diff: int
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_ms: int
    source_file: Optional[str] = None
    error_summary: Optional[str] = None
    created_at: Optional[datetime] = None


class RunsListResponse(BaseModel):
    """Paginated list of pipeline runs."""
    items: List[PipelineRunSummary]
    total: int
    limit: int
    offset: int


class RunDetailResponse(PipelineRunSummary):
    """Detailed information for a specific pipeline execution attempt."""
    schema_evolution_events: List[EvolutionChangeSchema] = Field(default_factory=list)


# ==============================================================================
# Quarantine Schemas
# ==============================================================================

class QuarantineItem(BaseModel):
    """Quarantined record metadata and violation details."""
    quarantine_id: str
    run_id: str
    batch_id: str
    dataset_name: str
    row_index: int
    source_record_id: Optional[str] = None
    violation_field: Optional[str] = None
    violation_rule: Optional[str] = None
    error_message: Optional[str] = None
    source_file: Optional[str] = None
    quarantined_at: Optional[datetime] = None


class QuarantineListResponse(BaseModel):
    """Paginated list of quarantined record violations."""
    items: List[QuarantineItem]
    total: int
    limit: int
    offset: int


class QuarantineDetailResponse(QuarantineItem):
    """Detailed quarantine record including original raw record payload."""
    raw_record: Dict[str, Any] = Field(..., description="Original raw record payload as parsed JSON dictionary")


# ==============================================================================
# Metrics Schemas
# ==============================================================================

class DatasetMetrics(BaseModel):
    """Aggregated metrics for a single dataset."""
    dataset_name: str
    total_runs: int
    successful_runs: int
    partial_success_runs: int
    failed_runs: int
    schema_rejected_runs: int
    total_input_records: int
    total_published_records: int
    total_quarantined_records: int


class MetricsSummaryResponse(BaseModel):
    """System-wide operational and quality metrics."""
    total_runs: int
    successful_runs: int
    partial_success_runs: int
    failed_runs: int
    schema_rejected_runs: int
    total_input_records: int
    total_published_records: int
    total_rejected_records: int
    datasets: List[DatasetMetrics] = Field(default_factory=list)


# ==============================================================================
# Evolution Events Schemas
# ==============================================================================

class EvolutionEventItem(BaseModel):
    """Schema evolution event audit record."""
    event_id: str
    run_id: str
    batch_id: str
    dataset_name: str
    contract_version: Optional[str] = None
    change_type: str
    is_breaking: bool
    impact: str
    column_name: Optional[str] = None
    diff_details: Optional[str] = None
    detected_at: Optional[datetime] = None


class EvolutionEventsListResponse(BaseModel):
    """Paginated list of schema evolution events."""
    items: List[EvolutionEventItem]
    total: int
    limit: int
    offset: int


# ==============================================================================
# Common Error Schema
# ==============================================================================

class ErrorResponse(BaseModel):
    """Standardized error response payload."""
    detail: str
