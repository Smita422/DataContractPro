"""Tests for Synthetic Data Generator and Negative Data Injection."""

from pathlib import Path
import pandas as pd
import pytest

from schemaguard.core.contract import load_contract
from schemaguard.core.generator import SyntheticDataGenerator
from schemaguard.core.storage import DuckDBStorageManager
from schemaguard.core.validator import DataValidator


# ==============================================================================
# 1. Deterministic Reproducibility
# ==============================================================================

def test_deterministic_reproducibility(tmp_path: Path):
    """Verify that identical random seeds produce byte-identical datasets."""
    gen1 = SyntheticDataGenerator(seed=12345)
    file1 = tmp_path / "cust_seed1.csv"
    df1 = gen1.generate_customers(count=100, output_file=file1)

    gen2 = SyntheticDataGenerator(seed=12345)
    file2 = tmp_path / "cust_seed2.csv"
    df2 = gen2.generate_customers(count=100, output_file=file2)

    pd.testing.assert_frame_equal(df1, df2)
    assert file1.read_bytes() == file2.read_bytes()


def test_different_seeds_produce_different_data(tmp_path: Path):
    """Verify that different seeds produce distinct datasets."""
    gen1 = SyntheticDataGenerator(seed=1)
    df1 = gen1.generate_customers(count=50)

    gen2 = SyntheticDataGenerator(seed=2)
    df2 = gen2.generate_customers(count=50)

    # Emails and names should diverge
    assert not df1["email"].equals(df2["email"])


# ==============================================================================
# 2. Zero-Record and Boundary Generation
# ==============================================================================

def test_zero_record_generation(tmp_path: Path):
    """Verify that generating 0 records returns an empty DataFrame with exact contract columns."""
    gen = SyntheticDataGenerator(seed=42)
    file_path = tmp_path / "empty_cust.csv"
    df = gen.generate_customers(count=0, output_file=file_path)

    assert len(df) == 0
    assert list(df.columns) == [
        "customer_id", "customer_name", "email", "city", "customer_status", "created_at"
    ]
    assert file_path.exists()
    assert file_path.read_text().strip() == "customer_id,customer_name,email,city,customer_status,created_at"


def test_invalid_negative_count_raises_error():
    """Verify that negative record counts raise a ValueError."""
    gen = SyntheticDataGenerator()
    with pytest.raises(ValueError, match="count must be non-negative"):
        gen.generate_customers(count=-10)

    with pytest.raises(ValueError, match="count must be non-negative"):
        gen.generate_orders(count=-5)


# ==============================================================================
# 3. Scalability: 100,000 Record Generation
# ==============================================================================

def test_large_scale_customer_generation():
    """Verify fast generation of 100,000 clean customer records with contract compliance."""
    gen = SyntheticDataGenerator(seed=999)
    df = gen.generate_customers(count=100000)

    assert len(df) == 100000
    # Primary keys must be unique and non-null
    assert df["customer_id"].nunique() == 100000
    assert df["customer_id"].isnull().sum() == 0
    # Emails must be unique
    assert df["email"].nunique() == 100000
    # Statuses must adhere to enum
    assert set(df["customer_status"].unique()).issubset({"active", "inactive"})


# ==============================================================================
# 4. Customer-Order Foreign Key Relationship Integrity
# ==============================================================================

def test_order_customer_relationship_integrity(tmp_path: Path):
    """Verify that generated orders reference the provided customer IDs."""
    gen = SyntheticDataGenerator(seed=42)
    known_customers = ["CUST-0000001", "CUST-0000002", "CUST-0000003"]
    orders_df = gen.generate_orders(count=200, customer_ids=known_customers)

    assert len(orders_df) == 200
    assert set(orders_df["customer_id"].unique()).issubset(set(known_customers))
    assert orders_df["order_id"].nunique() == 200
    assert (orders_df["quantity"] >= 1).all()
    assert (orders_df["unit_price"] >= 0.0).all()


# ==============================================================================
# 5. Negative Data Injection Verification
# ==============================================================================

def test_controlled_customer_corruption(tmp_path: Path):
    """Verify that synthetic customer corruption injects detectable anomalies."""
    gen = SyntheticDataGenerator(seed=42)
    corrupted_df = gen.generate_customers(
        count=100,
        corruption_rate=0.20,
        corruption_options={
            "null_required_pct": 0.10,
            "invalid_enum_pct": 0.10,
            "invalid_timestamp_pct": 0.10,
        },
    )

    # Validate using core DataValidator
    contract = load_contract("customers")
    storage = DuckDBStorageManager(db_path=":memory:")
    valid_df, res = DataValidator.validate(
        raw_df=corrupted_df,
        contract=contract,
        batch_id="batch_cust_corrupt",
        run_id="run_cust_corrupt",
        source_file="corrupted_customers.csv",
        storage=storage,
    )

    assert res.rejected_count > 0
    assert len(res.quarantine_records) > 0

    violation_fields = {q.violation_field for q in res.quarantine_records}
    assert "customer_name" in violation_fields or "customer_status" in violation_fields or "created_at" in violation_fields


def test_controlled_order_corruption(tmp_path: Path):
    """Verify that synthetic order corruption injects detectable anomalies."""
    gen = SyntheticDataGenerator(seed=42)
    corrupted_df = gen.generate_orders(
        count=100,
        corruption_rate=0.25,
        corruption_options={
            "negative_qty_pct": 0.10,
            "negative_price_pct": 0.10,
            "invalid_enum_pct": 0.10,
            "invalid_fk_pct": 0.10,
        },
    )

    contract = load_contract("orders")
    storage = DuckDBStorageManager(db_path=":memory:")
    valid_df, res = DataValidator.validate(
        raw_df=corrupted_df,
        contract=contract,
        batch_id="batch_ord_corrupt",
        run_id="run_ord_corrupt",
        source_file="corrupted_orders.csv",
        storage=storage,
    )

    assert res.rejected_count > 0
    violation_rules = {q.violation_rule for q in res.quarantine_records}
    # Should catch min bounds or allowed values or foreign key
    assert any("min" in r or "allowed_values" in r or "foreign_key" in r for r in violation_rules)
