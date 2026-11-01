"""Data Contract discovery and retrieval endpoints."""

from typing import Optional
from fastapi import APIRouter, HTTPException, Query, status

from schemaguard.api.schemas import (
    ColumnDefinitionSchema,
    ConstraintRulesSchema,
    ContractDetailResponse,
    ContractsListResponse,
    DerivedFieldSchema,
)
from schemaguard.core.contract import (
    ContractNotFoundError,
    InvalidContractError,
    list_all_contracts,
    load_contract,
)
from schemaguard.utils.logger import logger

router = APIRouter(prefix="/contracts", tags=["Contracts"])


@router.get(
    "",
    response_model=ContractsListResponse,
    summary="List Registered Contracts",
    description="Returns all registered datasets and their corresponding active semantic versions.",
)
def list_contracts():
    """List all registered datasets and their version identifiers."""
    try:
        datasets_map = list_all_contracts()
        return ContractsListResponse(
            datasets=datasets_map,
            total_datasets=len(datasets_map),
        )
    except Exception as exc:
        logger.error(f"Failed to list data contracts: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve data contracts: {exc}",
        )


@router.get(
    "/{dataset}",
    response_model=ContractDetailResponse,
    summary="Get Contract by Dataset",
    description="Retrieve the complete schema, types, allowed values, constraints, and derived fields for a dataset.",
)
def get_contract(
    dataset: str,
    version: Optional[str] = Query(
        default=None,
        description="Optional semantic version (e.g. '1.0.0'). Defaults to latest active version if omitted.",
    ),
):
    """Retrieve full contract details for the requested dataset and optional version."""
    try:
        contract = load_contract(dataset_name=dataset, version=version)
    except ContractNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except InvalidContractError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Invalid contract configuration: {exc}",
        )
    except Exception as exc:
        logger.error(f"Unexpected error loading contract for '{dataset}': {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error loading contract: {exc}",
        )

    # Convert Pydantic core model to API response schema
    columns_schema = []
    for col in contract.columns:
        constraints_schema = None
        if col.constraints:
            constraints_schema = ConstraintRulesSchema(
                min=col.constraints.min,
                max=col.constraints.max,
                min_length=col.constraints.min_length,
                max_length=col.constraints.max_length,
                pattern=col.constraints.pattern,
                allowed_values=col.constraints.allowed_values,
            )
        columns_schema.append(
            ColumnDefinitionSchema(
                name=col.name,
                type=col.type,
                nullable=col.nullable,
                primary_key=col.primary_key,
                unique=col.unique,
                default=col.default,
                description=col.description,
                constraints=constraints_schema,
            )
        )

    derived_schema = [
        DerivedFieldSchema(
            name=df.name,
            type=df.type,
            expression=df.expression,
            description=df.description,
        )
        for df in contract.derived_fields
    ]

    return ContractDetailResponse(
        dataset=contract.dataset,
        version=contract.version,
        owner=contract.owner,
        domain=contract.domain,
        compatibility_mode=contract.compatibility_mode,
        description=contract.description,
        columns=columns_schema,
        derived_fields=derived_schema,
    )
