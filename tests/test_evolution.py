"""Unit tests for Schema Evolution Analyzer and Compatibility Rules Engine."""

import pandas as pd
import pytest
from schemaguard.core.contract import (
    ColumnDefinition,
    ConstraintRules,
    Contract,
    load_contract,
)
from schemaguard.core.evolution import (
    ChangeType,
    EvolutionClassification,
    SchemaEvolutionAnalyzer,
)


@pytest.fixture
def base_orders_contract() -> Contract:
    """Fixture providing orders v1.0.0 contract."""
    return load_contract("orders", version="1.0.0")


@pytest.fixture
def v11_orders_contract() -> Contract:
    """Fixture providing orders v1.1.0 contract."""
    return load_contract("orders", version="1.1.0")


def test_optional_column_addition_is_non_breaking(
    base_orders_contract: Contract, v11_orders_contract: Contract
):
    """Verify adding an optional nullable column (delivery_status) is classified as NON_BREAKING."""
    report = SchemaEvolutionAnalyzer.compare_contracts(base_orders_contract, v11_orders_contract)

    assert not report.is_breaking
    assert report.compatibility_status == "COMPATIBLE"
    assert len(report.changes) == 1

    change = report.changes[0]
    assert change.column_name == "delivery_status"
    assert change.change_type == ChangeType.COLUMN_ADDED
    assert change.classification == EvolutionClassification.NON_BREAKING


def test_mandatory_column_addition_is_breaking(base_orders_contract: Contract):
    """Verify adding a non-nullable column without default is classified as BREAKING."""
    modified_dict = base_orders_contract.model_dump()
    modified_dict["version"] = "2.0.0"
    modified_dict["columns"].append({
        "name": "warehouse_id",
        "type": "string",
        "nullable": False,  # Mandatory without default
    })
    target_contract = Contract(**modified_dict)

    report = SchemaEvolutionAnalyzer.compare_contracts(base_orders_contract, target_contract)
    assert report.is_breaking
    assert report.compatibility_status == "BREAKING"

    added_change = next(c for c in report.changes if c.column_name == "warehouse_id")
    assert added_change.change_type == ChangeType.COLUMN_ADDED
    assert added_change.classification == EvolutionClassification.BREAKING


def test_breaking_column_removal(base_orders_contract: Contract):
    """Verify removing an existing column is classified as BREAKING."""
    modified_dict = base_orders_contract.model_dump()
    modified_dict["version"] = "2.0.0"
    # Remove 'payment_method'
    modified_dict["columns"] = [
        c for c in modified_dict["columns"] if c["name"] != "payment_method"
    ]
    target_contract = Contract(**modified_dict)

    report = SchemaEvolutionAnalyzer.compare_contracts(base_orders_contract, target_contract)
    assert report.is_breaking
    removed_change = next(c for c in report.changes if c.column_name == "payment_method")
    assert removed_change.change_type == ChangeType.COLUMN_REMOVED
    assert removed_change.classification == EvolutionClassification.BREAKING


def test_column_renaming_is_breaking(base_orders_contract: Contract):
    """Verify explicit column renaming is classified as BREAKING for downstream queries."""
    modified_dict = base_orders_contract.model_dump()
    modified_dict["version"] = "2.0.0"
    # Rename 'unit_price' -> 'item_price'
    for c in modified_dict["columns"]:
        if c["name"] == "unit_price":
            c["name"] = "item_price"
    target_contract = Contract(**modified_dict)

    report = SchemaEvolutionAnalyzer.compare_contracts(
        base_orders_contract,
        target_contract,
        renamed_columns={"unit_price": "item_price"},
    )
    assert report.is_breaking
    rename_change = next(c for c in report.changes if c.change_type == ChangeType.COLUMN_RENAMED)
    assert rename_change.column_name == "item_price"
    assert rename_change.classification == EvolutionClassification.BREAKING


def test_incompatible_type_change(base_orders_contract: Contract):
    """Verify incompatible type modification (e.g. string to integer) is classified as BREAKING."""
    modified_dict = base_orders_contract.model_dump()
    modified_dict["version"] = "2.0.0"
    for c in modified_dict["columns"]:
        if c["name"] == "product_name":
            c["type"] = "integer"  # string -> integer is incompatible
    target_contract = Contract(**modified_dict)

    report = SchemaEvolutionAnalyzer.compare_contracts(base_orders_contract, target_contract)
    assert report.is_breaking
    type_change = next(c for c in report.changes if c.column_name == "product_name")
    assert type_change.change_type == ChangeType.TYPE_CHANGED
    assert type_change.classification == EvolutionClassification.BREAKING


def test_safe_type_widening(base_orders_contract: Contract):
    """Verify safe type widening (e.g. integer to float) is classified as NON_BREAKING."""
    modified_dict = base_orders_contract.model_dump()
    modified_dict["version"] = "1.1.0"
    for c in modified_dict["columns"]:
        if c["name"] == "quantity":
            c["type"] = "float"  # integer -> float safe widening
    target_contract = Contract(**modified_dict)

    report = SchemaEvolutionAnalyzer.compare_contracts(base_orders_contract, target_contract)
    assert not report.is_breaking
    type_change = next(c for c in report.changes if c.column_name == "quantity")
    assert type_change.change_type == ChangeType.TYPE_CHANGED
    assert type_change.classification == EvolutionClassification.NON_BREAKING


def test_nullable_to_non_nullable(base_orders_contract: Contract):
    """Verify tightening nullability (nullable -> non-nullable) is classified as BREAKING."""
    # First make quantity nullable in base, then non-nullable in target
    base_dict = base_orders_contract.model_dump()
    for c in base_dict["columns"]:
        if c["name"] == "product_name":
            c["nullable"] = True
    c_base = Contract(**base_dict)

    target_dict = base_orders_contract.model_dump()
    for c in target_dict["columns"]:
        if c["name"] == "product_name":
            c["nullable"] = False
    c_target = Contract(**target_dict)

    report = SchemaEvolutionAnalyzer.compare_contracts(c_base, c_target)
    assert report.is_breaking
    null_change = next(c for c in report.changes if c.column_name == "product_name")
    assert null_change.change_type == ChangeType.NULLABILITY_CHANGED
    assert null_change.classification == EvolutionClassification.BREAKING


def test_non_nullable_to_nullable(base_orders_contract: Contract):
    """Verify relaxing nullability (non-nullable -> nullable) is classified as NON_BREAKING."""
    target_dict = base_orders_contract.model_dump()
    for c in target_dict["columns"]:
        if c["name"] == "product_name":
            c["nullable"] = True  # Relaxed to nullable
    c_target = Contract(**target_dict)

    report = SchemaEvolutionAnalyzer.compare_contracts(base_orders_contract, c_target)
    assert not report.is_breaking
    null_change = next(c for c in report.changes if c.column_name == "product_name")
    assert null_change.change_type == ChangeType.NULLABILITY_CHANGED
    assert null_change.classification == EvolutionClassification.NON_BREAKING


def test_enum_expansion_is_non_breaking(base_orders_contract: Contract):
    """Verify adding an allowed enum value is classified as NON_BREAKING."""
    target_dict = base_orders_contract.model_dump()
    for c in target_dict["columns"]:
        if c["name"] == "order_status":
            c["constraints"]["allowed_values"].append("AWAITING_PAYMENT")
    c_target = Contract(**target_dict)

    report = SchemaEvolutionAnalyzer.compare_contracts(base_orders_contract, c_target)
    assert not report.is_breaking
    enum_change = next(c for c in report.changes if c.column_name == "order_status")
    assert enum_change.change_type == ChangeType.ALLOWED_VALUES_CHANGED
    assert enum_change.classification == EvolutionClassification.NON_BREAKING


def test_enum_restriction_is_breaking(base_orders_contract: Contract):
    """Verify removing an allowed enum value is classified as BREAKING."""
    target_dict = base_orders_contract.model_dump()
    for c in target_dict["columns"]:
        if c["name"] == "order_status":
            # Remove cancelled
            c["constraints"]["allowed_values"] = [
                v for v in c["constraints"]["allowed_values"] if v != "cancelled"
            ]
    c_target = Contract(**target_dict)

    report = SchemaEvolutionAnalyzer.compare_contracts(base_orders_contract, c_target)
    assert report.is_breaking
    enum_change = next(c for c in report.changes if c.column_name == "order_status")
    assert enum_change.change_type == ChangeType.ALLOWED_VALUES_CHANGED
    assert enum_change.classification == EvolutionClassification.BREAKING


def test_primary_key_change_is_breaking(base_orders_contract: Contract):
    """Verify changing primary key definition is classified as BREAKING."""
    target_dict = base_orders_contract.model_dump()
    for c in target_dict["columns"]:
        if c["name"] == "order_id":
            c["primary_key"] = False
        if c["name"] == "customer_id":
            c["primary_key"] = True
    c_target = Contract(**target_dict)

    report = SchemaEvolutionAnalyzer.compare_contracts(base_orders_contract, c_target)
    assert report.is_breaking
    pk_change = next(c for c in report.changes if c.change_type == ChangeType.PRIMARY_KEY_CHANGED)
    assert pk_change.classification == EvolutionClassification.BREAKING


def test_batch_strict_mode_unexpected_column(base_orders_contract: Contract):
    """Verify unexpected column in STRICT mode is classified as BREAKING."""
    df = pd.DataFrame([
        {
            "order_id": "ORD-12345",
            "customer_id": "CUST-0001",
            "order_date": "2026-11-01 12:00:00",
            "product_name": "Keyboard",
            "quantity": 2,
            "unit_price": 49.99,
            "order_status": "COMPLETED",
            "payment_method": "CREDIT_CARD",
            "updated_at": "2026-11-01 12:05:00",
            "unknown_metadata_field": "unregistered_value",  # Unexpected
        }
    ])

    report = SchemaEvolutionAnalyzer.compare_batch_to_contract(
        df, base_orders_contract, mode="STRICT"
    )
    assert report.is_breaking
    change = next(c for c in report.changes if c.column_name == "unknown_metadata_field")
    assert change.change_type == ChangeType.UNEXPECTED_COLUMN
    assert change.classification == EvolutionClassification.BREAKING


def test_batch_permissive_mode_unexpected_column(base_orders_contract: Contract):
    """Verify unexpected column in PERMISSIVE mode is classified as NON_BREAKING."""
    df = pd.DataFrame([
        {
            "order_id": "ORD-12345",
            "customer_id": "CUST-0001",
            "order_date": "2026-11-01 12:00:00",
            "product_name": "Keyboard",
            "quantity": 2,
            "unit_price": 49.99,
            "order_status": "COMPLETED",
            "payment_method": "CREDIT_CARD",
            "updated_at": "2026-11-01 12:05:00",
            "extra_field": "sample",
        }
    ])

    report = SchemaEvolutionAnalyzer.compare_batch_to_contract(
        df, base_orders_contract, mode="PERMISSIVE"
    )
    assert not report.is_breaking
    change = next(c for c in report.changes if c.column_name == "extra_field")
    assert change.change_type == ChangeType.UNEXPECTED_COLUMN
    assert change.classification == EvolutionClassification.NON_BREAKING


def test_batch_missing_required_column(base_orders_contract: Contract):
    """Verify missing required column in batch is classified as BREAKING."""
    df = pd.DataFrame([
        {
            "order_id": "ORD-12345",
            # customer_id is missing!
            "order_date": "2026-11-01 12:00:00",
            "product_name": "Keyboard",
            "quantity": 2,
            "unit_price": 49.99,
            "order_status": "COMPLETED",
            "payment_method": "CREDIT_CARD",
            "updated_at": "2026-11-01 12:05:00",
        }
    ])

    report = SchemaEvolutionAnalyzer.compare_batch_to_contract(
        df, base_orders_contract, mode="PERMISSIVE"
    )
    assert report.is_breaking
    change = next(c for c in report.changes if c.column_name == "customer_id")
    assert change.change_type == ChangeType.COLUMN_REMOVED
    assert change.classification == EvolutionClassification.BREAKING
