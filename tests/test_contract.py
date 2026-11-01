"""Unit tests for Data Contract models, YAML parsing, and resolution."""

from pathlib import Path
import pytest
from schemaguard.core.contract import (
    Contract,
    ContractNotFoundError,
    InvalidContractError,
    list_all_contracts,
    list_dataset_contracts,
    load_contract,
    load_contract_from_yaml,
)


def test_load_valid_customers_contract():
    """Verify loading and validating the customers v1.0.0 contract."""
    contract = load_contract("customers", version="1.0.0")
    assert contract.dataset == "customers"
    assert contract.version == "1.0.0"
    assert contract.compatibility_mode == "BACKWARD"
    assert contract.get_primary_key() == "customer_id"

    # Verify column definitions
    cust_id = contract.get_column("customer_id")
    assert cust_id is not None
    assert cust_id.nullable is False
    assert cust_id.constraints is not None
    assert cust_id.constraints.pattern == "^CUST-[0-9]{4,}$"

    status_col = contract.get_column("customer_status")
    assert status_col is not None
    assert status_col.constraints is not None
    assert "active" in status_col.constraints.allowed_values


def test_load_valid_orders_contracts():
    """Verify loading and validating orders v1.0.0 and v1.1.0 contracts."""
    contract_v10 = load_contract("orders", version="1.0.0")
    assert contract_v10.dataset == "orders"
    assert contract_v10.version == "1.0.0"
    assert contract_v10.get_primary_key() == "order_id"
    assert contract_v10.get_column("delivery_status") is None
    assert len(contract_v10.derived_fields) == 1
    assert contract_v10.derived_fields[0].name == "total_amount"

    # v1.1.0 introduces optional delivery_status
    contract_v11 = load_contract("orders", version="1.1.0")
    assert contract_v11.version == "1.1.0"
    delivery_col = contract_v11.get_column("delivery_status")
    assert delivery_col is not None
    assert delivery_col.nullable is True
    assert "in_transit" in delivery_col.constraints.allowed_values


def test_contract_latest_version_resolution():
    """Verify automatic resolution of the latest semver contract."""
    latest_orders = load_contract("orders")  # None defaults to latest
    assert latest_orders.version == "1.1.0"


def test_contract_missing_dataset_or_version():
    """Verify clear exceptions when requesting missing datasets or versions."""
    with pytest.raises(ContractNotFoundError, match="No contracts directory found"):
        load_contract("non_existent_dataset")

    with pytest.raises(ContractNotFoundError, match="Contract version '9.9.9' not found"):
        load_contract("orders", version="9.9.9")


def test_invalid_yaml_syntax(tmp_path: Path):
    """Verify InvalidContractError when YAML is malformed."""
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("dataset: orders\nversion: [broken yaml", encoding="utf-8")

    with pytest.raises(InvalidContractError, match="YAML parsing error"):
        load_contract_from_yaml(bad_yaml)


def test_invalid_contract_schema(tmp_path: Path):
    """Verify InvalidContractError on semantic/validation errors (e.g. min > max, duplicate cols)."""
    # 1. Invalid bounds
    bad_bounds_yaml = tmp_path / "bad_bounds.yaml"
    bad_bounds_yaml.write_text(
        """
dataset: "test"
version: "1.0.0"
owner: "team"
columns:
  - name: "price"
    type: "float"
    constraints:
      min: 100.0
      max: 10.0
""",
        encoding="utf-8",
    )
    with pytest.raises(InvalidContractError, match="min .* cannot be greater than max"):
        load_contract_from_yaml(bad_bounds_yaml)

    # 2. Duplicate columns
    duplicate_col_yaml = tmp_path / "duplicate_cols.yaml"
    duplicate_col_yaml.write_text(
        """
dataset: "test"
version: "1.0.0"
owner: "team"
columns:
  - name: "id"
    type: "string"
  - name: "id"
    type: "integer"
""",
        encoding="utf-8",
    )
    with pytest.raises(InvalidContractError, match="Duplicate column names"):
        load_contract_from_yaml(duplicate_col_yaml)


def test_list_all_and_dataset_contracts():
    """Verify discovery utilities for dataset contracts."""
    all_contracts = list_all_contracts()
    assert "customers" in all_contracts
    assert "orders" in all_contracts
    assert "1.0.0" in all_contracts["customers"]
    assert "1.0.0" in all_contracts["orders"]
    assert "1.1.0" in all_contracts["orders"]

    orders_versions = list_dataset_contracts("orders")
    assert orders_versions == ["1.0.0", "1.1.0"]
