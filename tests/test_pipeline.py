"""Comprehensive end-to-end integration test suite for the SchemaGuard validation and pipeline engine."""

from datetime import datetime
from pathlib import Path
import pytest
import pandas as pd

from schemaguard.core.pipeline import PipelineOrchestrator
from schemaguard.core.storage import DuckDBStorageManager


@pytest.fixture
def temp_storage(tmp_path: Path) -> DuckDBStorageManager:
    """Provide an isolated DuckDB storage instance in a temporary folder."""
    db_file = tmp_path / "test_schemaguard.duckdb"
    return DuckDBStorageManager(db_path=db_file)


@pytest.fixture
def orchestrator(temp_storage: DuckDBStorageManager) -> PipelineOrchestrator:
    """Provide a PipelineOrchestrator wired to the isolated temporary storage."""
    return PipelineOrchestrator(storage=temp_storage)


# Helper to write CSV files for testing
def create_csv(tmp_path: Path, filename: str, rows: list[dict]) -> Path:
    p = tmp_path / filename
    df = pd.DataFrame(rows)
    df.to_csv(p, index=False)
    return p


# 1. Valid customer batch
def test_valid_customer_batch(orchestrator: PipelineOrchestrator, tmp_path: Path):
    file_path = create_csv(
        tmp_path,
        "customers_valid.csv",
        [
            {
                "customer_id": "CUST-0001",
                "customer_name": "Alice Green",
                "email": "alice@example.com",
                "city": "Austin",
                "customer_status": "active",
                "created_at": "2026-11-01 10:00:00",
            },
            {
                "customer_id": "CUST-0002",
                "customer_name": "Bob Blue",
                "email": "bob@example.com",
                "city": "Boston",
                "customer_status": "inactive",
                "created_at": "2026-11-01 10:30:00",
            },
        ],
    )

    res = orchestrator.run(file_path, "customers")
    assert res.status == "SUCCESS"
    assert res.total_records == 2
    assert res.valid_records == 2
    assert res.quarantined_records == 0
    assert res.published_records == 2
    assert res.reconciliation_diff == 0

    # Verify rows in DuckDB
    rows = orchestrator.storage.fetch_all("SELECT customer_id, customer_name, email FROM published_customers")
    assert len(rows) == 2
    assert rows[0][0] == "CUST-0001"


# 2. Valid order batch (with derived field calculation and lineage)
def test_valid_order_batch(orchestrator: PipelineOrchestrator, tmp_path: Path):
    # Pre-populate customer to satisfy foreign key
    cust_file = create_csv(
        tmp_path,
        "customers_prep.csv",
        [{
            "customer_id": "CUST-0001",
            "customer_name": "Alice Green",
            "email": "alice@example.com",
            "city": "Austin",
            "customer_status": "active",
            "created_at": "2026-11-01 10:00:00",
        }],
    )
    orchestrator.run(cust_file, "customers")

    order_file = create_csv(
        tmp_path,
        "orders_valid.csv",
        [{
            "order_id": "ORD-00001",
            "customer_id": "CUST-0001",
            "order_date": "2026-11-01 11:00:00",
            "product_name": "Mechanical Keyboard",
            "quantity": "3",
            "unit_price": "99.50",
            "order_status": "delivered",
            "payment_method": "card",
            "updated_at": "2026-11-01 11:05:00",
        }],
    )

    res = orchestrator.run(order_file, "orders")
    assert res.status == "SUCCESS"
    assert res.valid_records == 1
    assert res.quarantined_records == 0

    # Verify total_amount derived field = 3 * 99.50 = 298.50
    order_row = orchestrator.storage.fetch_one(
        "SELECT order_id, quantity, unit_price, total_amount, _sg_batch_id FROM published_orders WHERE order_id = 'ORD-00001'"
    )
    assert order_row[0] == "ORD-00001"
    assert order_row[1] == 3
    assert order_row[2] == 99.50
    assert order_row[3] == 298.50
    assert order_row[4].startswith("batch_orders_")


# 3. Empty input
def test_empty_input(orchestrator: PipelineOrchestrator, tmp_path: Path):
    empty_file = tmp_path / "empty.csv"
    empty_file.write_bytes(b"")

    res = orchestrator.run(empty_file, "customers")
    assert res.status == "FAILED"
    assert "empty" in res.error_summary.lower()


# 4. Missing required columns
def test_missing_required_columns(orchestrator: PipelineOrchestrator, tmp_path: Path):
    # Missing 'customer_name'
    file_path = create_csv(
        tmp_path,
        "customers_missing_col.csv",
        [{
            "customer_id": "CUST-0001",
            "email": "alice@example.com",
            "customer_status": "ACTIVE",
            "created_at": "2026-11-01 10:00:00",
        }],
    )
    res = orchestrator.run(file_path, "customers")
    assert res.status == "SCHEMA_REJECTED"
    assert res.published_records == 0


# 5. Null required fields
def test_null_required_fields(orchestrator: PipelineOrchestrator, tmp_path: Path):
    file_path = create_csv(
        tmp_path,
        "customers_null_field.csv",
        [{
            "customer_id": "CUST-0001",
            "customer_name": "",  # Empty/null!
            "email": "alice@example.com",
            "city": "Austin",
            "customer_status": "ACTIVE",
            "created_at": "2026-11-01 10:00:00",
        }],
    )
    res = orchestrator.run(file_path, "customers")
    assert res.status == "PARTIAL_SUCCESS"
    assert res.valid_records == 0
    assert res.quarantined_records == 1

    q_row = orchestrator.storage.fetch_one("SELECT violation_field, violation_rule FROM quarantined_records")
    assert q_row[0] == "customer_name"
    assert q_row[1] == "not_null"


# 6. Incorrect data types
def test_incorrect_data_types(orchestrator: PipelineOrchestrator, tmp_path: Path):
    cust_file = create_csv(
        tmp_path,
        "cust_prep_types.csv",
        [{
            "customer_id": "CUST-0001",
            "customer_name": "Alice Green",
            "email": "alice@example.com",
            "city": "Austin",
            "customer_status": "active",
            "created_at": "2026-11-01 10:00:00",
        }],
    )
    orchestrator.run(cust_file, "customers")

    file_path = create_csv(
        tmp_path,
        "orders_bad_type.csv",
        [{
            "order_id": "ORD-00001",
            "customer_id": "CUST-0001",
            "order_date": "2026-11-01 11:00:00",
            "product_name": "Keyboard",
            "quantity": "five",  # Invalid int
            "unit_price": "99.50",
            "order_status": "pending",
            "payment_method": "card",
            "updated_at": "2026-11-01 11:05:00",
        }],
    )
    res = orchestrator.run(file_path, "orders")
    assert res.status == "PARTIAL_SUCCESS"
    assert res.quarantined_records == 1
    q_row = orchestrator.storage.fetch_one("SELECT violation_field, violation_rule FROM quarantined_records WHERE run_id = $1", [res.run_id])
    assert q_row[0] == "quantity"
    assert q_row[1] == "type: integer"


# 7. Invalid enum values
def test_invalid_enum_values(orchestrator: PipelineOrchestrator, tmp_path: Path):
    file_path = create_csv(
        tmp_path,
        "customers_bad_enum.csv",
        [{
            "customer_id": "CUST-0001",
            "customer_name": "Alice Green",
            "email": "alice@example.com",
            "city": "Austin",
            "customer_status": "BANNED",  # Invalid enum
            "created_at": "2026-11-01 10:00:00",
        }],
    )
    res = orchestrator.run(file_path, "customers")
    assert res.status == "PARTIAL_SUCCESS"
    assert res.quarantined_records == 1
    q_row = orchestrator.storage.fetch_one("SELECT violation_field, violation_rule FROM quarantined_records")
    assert q_row[0] == "customer_status"
    assert q_row[1] == "allowed_values"


# 8. Duplicate customer IDs
def test_duplicate_customer_ids(orchestrator: PipelineOrchestrator, tmp_path: Path):
    file_path = create_csv(
        tmp_path,
        "customers_dup_pk.csv",
        [
            {
                "customer_id": "CUST-0001",
                "customer_name": "Alice First",
                "email": "alice1@example.com",
                "city": "Austin",
                "customer_status": "ACTIVE",
                "created_at": "2026-11-01 10:00:00",
            },
            {
                "customer_id": "CUST-0001",  # Duplicate PK
                "customer_name": "Alice Second",
                "email": "alice2@example.com",
                "city": "Austin",
                "customer_status": "ACTIVE",
                "created_at": "2026-11-01 10:00:00",
            },
        ],
    )
    res = orchestrator.run(file_path, "customers")
    assert res.status == "PARTIAL_SUCCESS"
    assert res.quarantined_records == 2
    assert res.valid_records == 0


# 9. Duplicate order IDs
def test_duplicate_order_ids(orchestrator: PipelineOrchestrator, tmp_path: Path):
    cust_file = create_csv(
        tmp_path,
        "cust_prep_dup_orders.csv",
        [{
            "customer_id": "CUST-0001",
            "customer_name": "Alice Green",
            "email": "alice@example.com",
            "city": "Austin",
            "customer_status": "active",
            "created_at": "2026-11-01 10:00:00",
        }],
    )
    orchestrator.run(cust_file, "customers")

    file_path = create_csv(
        tmp_path,
        "orders_dup_pk.csv",
        [
            {
                "order_id": "ORD-00001",
                "customer_id": "CUST-0001",
                "order_date": "2026-11-01 11:00:00",
                "product_name": "Item A",
                "quantity": "1",
                "unit_price": "10.0",
                "order_status": "pending",
                "payment_method": "upi",
                "updated_at": "2026-11-01 11:05:00",
            },
            {
                "order_id": "ORD-00001",  # Duplicate PK
                "customer_id": "CUST-0001",
                "order_date": "2026-11-01 11:00:00",
                "product_name": "Item B",
                "quantity": "2",
                "unit_price": "20.0",
                "order_status": "pending",
                "payment_method": "upi",
                "updated_at": "2026-11-01 11:05:00",
            },
        ],
    )
    res = orchestrator.run(file_path, "orders")
    assert res.quarantined_records == 2
    assert res.valid_records == 0


# 10. Duplicate customer emails
def test_duplicate_customer_emails(orchestrator: PipelineOrchestrator, tmp_path: Path):
    file_path = create_csv(
        tmp_path,
        "customers_dup_email.csv",
        [
            {
                "customer_id": "CUST-0001",
                "customer_name": "Alice First",
                "email": "shared@example.com",
                "city": "Austin",
                "customer_status": "active",
                "created_at": "2026-11-01 10:00:00",
            },
            {
                "customer_id": "CUST-0002",
                "customer_name": "Bob Blue",
                "email": "shared@example.com",  # Duplicate unique email
                "city": "Boston",
                "customer_status": "active",
                "created_at": "2026-11-01 10:00:00",
            },
        ],
    )
    res = orchestrator.run(file_path, "customers")
    assert res.quarantined_records == 2
    assert res.valid_records == 0
    q_row = orchestrator.storage.fetch_one("SELECT violation_field, violation_rule FROM quarantined_records")
    assert q_row[0] == "email"
    assert q_row[1] == "unique"


# 11. Invalid foreign keys
def test_invalid_foreign_keys(orchestrator: PipelineOrchestrator, tmp_path: Path):
    # Pre-populate CUST-0001 only
    cust_file = create_csv(
        tmp_path,
        "cust_fk_prep.csv",
        [{
            "customer_id": "CUST-0001",
            "customer_name": "Alice Green",
            "email": "alice@example.com",
            "city": "Austin",
            "customer_status": "active",
            "created_at": "2026-11-01 10:00:00",
        }],
    )
    orchestrator.run(cust_file, "customers")

    # Order references non-existent CUST-9999
    order_file = create_csv(
        tmp_path,
        "orders_bad_fk.csv",
        [{
            "order_id": "ORD-00001",
            "customer_id": "CUST-9999",  # Does not exist!
            "order_date": "2026-11-01 11:00:00",
            "product_name": "Keyboard",
            "quantity": "1",
            "unit_price": "50.0",
            "order_status": "pending",
            "payment_method": "upi",
            "updated_at": "2026-11-01 11:05:00",
        }],
    )
    res = orchestrator.run(order_file, "orders")
    assert res.quarantined_records == 1
    assert res.valid_records == 0
    q_row = orchestrator.storage.fetch_one("SELECT violation_field, violation_rule FROM quarantined_records WHERE run_id = $1", [res.run_id])
    assert q_row[0] == "customer_id"
    assert "foreign_key" in q_row[1]


# 12. Negative quantity
def test_negative_quantity(orchestrator: PipelineOrchestrator, tmp_path: Path):
    cust_file = create_csv(
        tmp_path,
        "cust_prep_qty.csv",
        [{
            "customer_id": "CUST-0001",
            "customer_name": "Alice Green",
            "email": "alice@example.com",
            "city": "Austin",
            "customer_status": "active",
            "created_at": "2026-11-01 10:00:00",
        }],
    )
    orchestrator.run(cust_file, "customers")

    file_path = create_csv(
        tmp_path,
        "orders_neg_qty.csv",
        [{
            "order_id": "ORD-00001",
            "customer_id": "CUST-0001",
            "order_date": "2026-11-01 11:00:00",
            "product_name": "Keyboard",
            "quantity": "-2",  # Negative quantity
            "unit_price": "50.0",
            "order_status": "pending",
            "payment_method": "cash",
            "updated_at": "2026-11-01 11:05:00",
        }],
    )
    res = orchestrator.run(file_path, "orders")
    assert res.quarantined_records == 1
    q_row = orchestrator.storage.fetch_one("SELECT violation_field, violation_rule FROM quarantined_records WHERE run_id = $1", [res.run_id])
    assert q_row[0] == "quantity"
    assert q_row[1] == "min: 1.0"


# 13. Negative unit price
def test_negative_unit_price(orchestrator: PipelineOrchestrator, tmp_path: Path):
    cust_file = create_csv(
        tmp_path,
        "cust_prep_price.csv",
        [{
            "customer_id": "CUST-0001",
            "customer_name": "Alice Green",
            "email": "alice@example.com",
            "city": "Austin",
            "customer_status": "active",
            "created_at": "2026-11-01 10:00:00",
        }],
    )
    orchestrator.run(cust_file, "customers")

    file_path = create_csv(
        tmp_path,
        "orders_neg_price.csv",
        [{
            "order_id": "ORD-00001",
            "customer_id": "CUST-0001",
            "order_date": "2026-11-01 11:00:00",
            "product_name": "Keyboard",
            "quantity": "1",
            "unit_price": "-15.0",  # Negative price
            "order_status": "pending",
            "payment_method": "card",
            "updated_at": "2026-11-01 11:05:00",
        }],
    )
    res = orchestrator.run(file_path, "orders")
    assert res.quarantined_records == 1
    q_row = orchestrator.storage.fetch_one("SELECT violation_field, violation_rule FROM quarantined_records WHERE run_id = $1", [res.run_id])
    assert q_row[0] == "unit_price"
    assert q_row[1] == "min: 0.0"


# 14. Malformed timestamps
def test_malformed_timestamps(orchestrator: PipelineOrchestrator, tmp_path: Path):
    cust_file = create_csv(
        tmp_path,
        "cust_prep_ts.csv",
        [{
            "customer_id": "CUST-0001",
            "customer_name": "Alice Green",
            "email": "alice@example.com",
            "city": "Austin",
            "customer_status": "active",
            "created_at": "2026-11-01 10:00:00",
        }],
    )
    orchestrator.run(cust_file, "customers")

    file_path = create_csv(
        tmp_path,
        "orders_bad_timestamp.csv",
        [{
            "order_id": "ORD-00001",
            "customer_id": "CUST-0001",
            "order_date": "not-a-valid-date",  # Malformed
            "product_name": "Keyboard",
            "quantity": "1",
            "unit_price": "50.0",
            "order_status": "pending",
            "payment_method": "card",
            "updated_at": "2026-11-01 11:05:00",
        }],
    )
    res = orchestrator.run(file_path, "orders")
    assert res.quarantined_records == 1
    q_row = orchestrator.storage.fetch_one("SELECT violation_field, violation_rule FROM quarantined_records WHERE run_id = $1", [res.run_id])
    assert q_row[0] == "order_date"
    assert q_row[1] == "type: timestamp"


# 15. Multiple errors in one record
def test_multiple_errors_in_one_record(orchestrator: PipelineOrchestrator, tmp_path: Path):
    cust_file = create_csv(
        tmp_path,
        "cust_prep_multi.csv",
        [{
            "customer_id": "CUST-0001",
            "customer_name": "Alice Green",
            "email": "alice@example.com",
            "city": "Austin",
            "customer_status": "active",
            "created_at": "2026-11-01 10:00:00",
        }],
    )
    orchestrator.run(cust_file, "customers")

    file_path = create_csv(
        tmp_path,
        "orders_multi_error.csv",
        [{
            "order_id": "ORD-00001",
            "customer_id": "CUST-0001",
            "order_date": "bad_date",      # Error 1
            "product_name": "Keyboard",
            "quantity": "-5",              # Error 2
            "unit_price": "50.0",
            "order_status": "ILLEGAL_STATUS",  # Error 3
            "payment_method": "BITCOIN",       # Error 4
            "updated_at": "2026-11-01 11:05:00",
        }],
    )
    res = orchestrator.run(file_path, "orders")
    assert res.total_records == 1
    assert res.quarantined_records == 1  # 1 distinct record rejected

    # But multiple diagnostic violation entries created!
    violations = orchestrator.storage.fetch_all(
        "SELECT violation_field FROM quarantined_records WHERE run_id = $1", [res.run_id]
    )
    violation_fields = {v[0] for v in violations}
    assert "quantity" in violation_fields
    assert "order_status" in violation_fields
    assert "payment_method" in violation_fields
    assert "order_date" in violation_fields


# 16. Breaking schema rejection
def test_breaking_schema_rejection(orchestrator: PipelineOrchestrator, tmp_path: Path):
    # Customer CSV with completely unexpected extra column under STRICT mode
    file_path = create_csv(
        tmp_path,
        "customers_strict_extra.csv",
        [{
            "customer_id": "CUST-0001",
            "customer_name": "Alice Green",
            "email": "alice@example.com",
            "city": "Austin",
            "customer_status": "ACTIVE",
            "created_at": "2026-11-01 10:00:00",
            "unauthorized_field": "breach",
        }],
    )
    res = orchestrator.run(file_path, "customers", mode="STRICT")
    assert res.status == "SCHEMA_REJECTED"
    assert res.published_records == 0


# 17. Non-breaking schema evolution
def test_non_breaking_schema_evolution(orchestrator: PipelineOrchestrator, tmp_path: Path):
    # Order CSV with delivery_status against orders v1.1.0 contract
    cust_file = create_csv(
        tmp_path,
        "cust_v11.csv",
        [{
            "customer_id": "CUST-0001",
            "customer_name": "Alice Green",
            "email": "alice@example.com",
            "city": "Austin",
            "customer_status": "ACTIVE",
            "created_at": "2026-11-01 10:00:00",
        }],
    )
    orchestrator.run(cust_file, "customers")

    order_file = create_csv(
        tmp_path,
        "orders_v11.csv",
        [{
            "order_id": "ORD-00001",
            "customer_id": "CUST-0001",
            "order_date": "2026-11-01 11:00:00",
            "product_name": "Keyboard",
            "quantity": "2",
            "unit_price": "75.0",
            "order_status": "delivered",
            "payment_method": "card",
            "updated_at": "2026-11-01 11:05:00",
            "delivery_status": "in_transit",  # Non-breaking optional field
        }],
    )
    res = orchestrator.run(order_file, "orders", version="1.1.0")
    assert res.status == "SUCCESS"
    assert res.published_records == 1

    row = orchestrator.storage.fetch_one("SELECT delivery_status FROM published_orders WHERE order_id = 'ORD-00001'")
    assert row[0] == "in_transit"


# 18. Same batch processed twice (idempotency)
def test_same_batch_processed_twice(orchestrator: PipelineOrchestrator, tmp_path: Path):
    file_path = create_csv(
        tmp_path,
        "customers_idempotent.csv",
        [{
            "customer_id": "CUST-0001",
            "customer_name": "Alice Green",
            "email": "alice@example.com",
            "city": "Austin",
            "customer_status": "ACTIVE",
            "created_at": "2026-11-01 10:00:00",
        }],
    )

    # First run
    res1 = orchestrator.run(file_path, "customers")
    assert res1.status == "SUCCESS"
    assert res1.inserted_records == 1
    assert res1.updated_records == 0

    # Second run of identical batch
    res2 = orchestrator.run(file_path, "customers")
    assert res2.status == "SUCCESS"
    assert res2.batch_id == res1.batch_id          # Same batch_id
    assert res2.run_id != res1.run_id              # New distinct run_id
    assert res2.inserted_records == 0              # Zero new rows inserted
    assert res2.updated_records == 1               # Updated in-place (deduplicated)

    # Total row count in published_customers must remain 1
    total_db_rows = orchestrator.storage.fetch_one("SELECT COUNT(*) FROM published_customers")[0]
    assert total_db_rows == 1


# 19. Retry after failure
def test_retry_after_failure(orchestrator: PipelineOrchestrator, tmp_path: Path):
    bad_file = create_csv(
        tmp_path,
        "customers_failing.csv",
        [{
            "customer_id": "CUST-0001",
            "customer_name": "Alice Green",
            "email": "alice@example.com",
            "city": "Austin",
            "customer_status": "INVALID_STATE",  # Will fail
            "created_at": "2026-11-01 10:00:00",
        }],
    )
    res_fail = orchestrator.run(bad_file, "customers")
    assert res_fail.status == "PARTIAL_SUCCESS"
    assert res_fail.valid_records == 0
    assert orchestrator.storage.fetch_one("SELECT COUNT(*) FROM published_customers")[0] == 0

    # Upstream fixes the file
    fixed_file = create_csv(
        tmp_path,
        "customers_fixed.csv",
        [{
            "customer_id": "CUST-0001",
            "customer_name": "Alice Green",
            "email": "alice@example.com",
            "city": "Austin",
            "customer_status": "ACTIVE",  # Fixed
            "created_at": "2026-11-01 10:00:00",
        }],
    )
    res_ok = orchestrator.run(fixed_file, "customers")
    assert res_ok.status == "SUCCESS"
    assert res_ok.valid_records == 1
    assert orchestrator.storage.fetch_one("SELECT COUNT(*) FROM published_customers")[0] == 1


# 20. Transaction rollback
def test_transaction_rollback(orchestrator: PipelineOrchestrator, tmp_path: Path, monkeypatch):
    file_path = create_csv(
        tmp_path,
        "customers_tx.csv",
        [{
            "customer_id": "CUST-0001",
            "customer_name": "Alice Green",
            "email": "alice@example.com",
            "city": "Austin",
            "customer_status": "ACTIVE",
            "created_at": "2026-11-01 10:00:00",
        }],
    )

    # Monkeypatch storage upsert to raise exception midway
    def broken_upsert(*args, **kwargs):
        raise RuntimeError("Simulated DB Disk Full during publish")

    monkeypatch.setattr(orchestrator.storage, "upsert_published_records", broken_upsert)

    with pytest.raises(RuntimeError, match="Simulated DB Disk Full"):
        orchestrator.run(file_path, "customers")

    # Confirm that zero dirty rows were committed
    count = orchestrator.storage.fetch_one("SELECT COUNT(*) FROM published_customers")[0]
    assert count == 0

    # Confirm run was recorded as FAILED
    run_status = orchestrator.storage.fetch_one("SELECT status FROM pipeline_runs")[0]
    assert run_status == "FAILED"


# 21. Source-to-target reconciliation
def test_source_to_target_reconciliation(orchestrator: PipelineOrchestrator, tmp_path: Path):
    file_path = create_csv(
        tmp_path,
        "customers_reconcile.csv",
        [
            # 2 Valid rows
            {
                "customer_id": "CUST-0001",
                "customer_name": "Alice Green",
                "email": "alice@example.com",
                "city": "Austin",
                "customer_status": "ACTIVE",
                "created_at": "2026-11-01 10:00:00",
            },
            {
                "customer_id": "CUST-0002",
                "customer_name": "Bob Blue",
                "email": "bob@example.com",
                "city": "Boston",
                "customer_status": "ACTIVE",
                "created_at": "2026-11-01 10:00:00",
            },
            # 1 Invalid row (null name)
            {
                "customer_id": "CUST-0003",
                "customer_name": "",
                "email": "charlie@example.com",
                "city": "Chicago",
                "customer_status": "ACTIVE",
                "created_at": "2026-11-01 10:00:00",
            },
        ],
    )
    res = orchestrator.run(file_path, "customers")
    assert res.total_records == 3
    assert res.valid_records == 2
    assert res.quarantined_records == 1
    assert res.reconciliation_diff == 0
    assert res.reconciliation_report is not None
    assert res.reconciliation_report.is_balanced is True
    assert "input_count = valid_count + rejected_count" in res.reconciliation_report.explanation


# 22. Late-arriving records
def test_late_arriving_records(orchestrator: PipelineOrchestrator, tmp_path: Path):
    # Customer batch published at T0
    cust_file = create_csv(
        tmp_path,
        "cust_t0.csv",
        [{
            "customer_id": "CUST-0001",
            "customer_name": "Alice Green",
            "email": "alice@example.com",
            "city": "Austin",
            "customer_status": "ACTIVE",
            "created_at": "2026-11-01 08:00:00",
        }],
    )
    orchestrator.run(cust_file, "customers")

    # Order arriving later at T1 referencing customer from T0
    order_file = create_csv(
        tmp_path,
        "orders_t1.csv",
        [{
            "order_id": "ORD-00001",
            "customer_id": "CUST-0001",
            "order_date": "2026-11-01 12:00:00",
            "product_name": "Keyboard",
            "quantity": "1",
            "unit_price": "89.0",
            "order_status": "delivered",
            "payment_method": "netbanking",
            "updated_at": "2026-11-01 12:05:00",
        }],
    )
    res = orchestrator.run(order_file, "orders")
    assert res.status == "SUCCESS"
    assert res.valid_records == 1


# 23. Dedicated FK: Existing published customer reference
def test_fk_existing_published_customer_reference(orchestrator: PipelineOrchestrator, tmp_path: Path):
    cust_file = create_csv(
        tmp_path,
        "fk_cust_exist.csv",
        [{"customer_id": "CUST-0001", "customer_name": "Alice", "email": "a@ex.com", "city": "NYC", "customer_status": "active", "created_at": "2026-11-01 10:00:00"}],
    )
    orchestrator.run(cust_file, "customers")

    order_file = create_csv(
        tmp_path,
        "fk_order_valid.csv",
        [{"order_id": "ORD-00001", "customer_id": "CUST-0001", "order_date": "2026-11-01 11:00:00", "product_name": "Item", "quantity": "1", "unit_price": "10.0", "order_status": "pending", "payment_method": "card", "updated_at": "2026-11-01 11:05:00"}],
    )
    res = orchestrator.run(order_file, "orders")
    assert res.status == "SUCCESS"
    assert res.valid_records == 1
    assert res.quarantined_records == 0


# 24. Dedicated FK: Unknown customer reference
def test_fk_unknown_customer_reference(orchestrator: PipelineOrchestrator, tmp_path: Path):
    cust_file = create_csv(
        tmp_path,
        "fk_cust_known.csv",
        [{"customer_id": "CUST-0001", "customer_name": "Alice", "email": "a@ex.com", "city": "NYC", "customer_status": "active", "created_at": "2026-11-01 10:00:00"}],
    )
    orchestrator.run(cust_file, "customers")

    order_file = create_csv(
        tmp_path,
        "fk_order_unknown.csv",
        [{"order_id": "ORD-00001", "customer_id": "CUST-9999", "order_date": "2026-11-01 11:00:00", "product_name": "Item", "quantity": "1", "unit_price": "10.0", "order_status": "pending", "payment_method": "card", "updated_at": "2026-11-01 11:05:00"}],
    )
    res = orchestrator.run(order_file, "orders")
    assert res.valid_records == 0
    assert res.quarantined_records == 1
    q_row = orchestrator.storage.fetch_one("SELECT error_message FROM quarantined_records WHERE run_id = $1", [res.run_id])
    assert "Referenced customer_id 'CUST-9999' does not exist in published_customers" in q_row[0]


# 25. Dedicated FK: Null customer reference
def test_fk_null_customer_reference(orchestrator: PipelineOrchestrator, tmp_path: Path):
    cust_file = create_csv(
        tmp_path,
        "fk_cust_present.csv",
        [{"customer_id": "CUST-0001", "customer_name": "Alice", "email": "a@ex.com", "city": "NYC", "customer_status": "active", "created_at": "2026-11-01 10:00:00"}],
    )
    orchestrator.run(cust_file, "customers")

    order_file = create_csv(
        tmp_path,
        "fk_order_null.csv",
        [{"order_id": "ORD-00001", "customer_id": "", "order_date": "2026-11-01 11:00:00", "product_name": "Item", "quantity": "1", "unit_price": "10.0", "order_status": "pending", "payment_method": "card", "updated_at": "2026-11-01 11:05:00"}],
    )
    res = orchestrator.run(order_file, "orders")
    assert res.valid_records == 0
    assert res.quarantined_records == 1
    q_rows = orchestrator.storage.fetch_all("SELECT violation_rule, error_message FROM quarantined_records WHERE run_id = $1", [res.run_id])
    rules = {r[0] for r in q_rows}
    assert "foreign_key: published_customers" in rules or "not_null" in rules


# 26. Dedicated FK: Order batch loaded before any customers
def test_fk_orders_loaded_before_customers(orchestrator: PipelineOrchestrator, tmp_path: Path):
    # Zero customers in database!
    order_file = create_csv(
        tmp_path,
        "fk_orders_before_customers.csv",
        [{"order_id": "ORD-00001", "customer_id": "CUST-0001", "order_date": "2026-11-01 11:00:00", "product_name": "Item", "quantity": "1", "unit_price": "10.0", "order_status": "pending", "payment_method": "card", "updated_at": "2026-11-01 11:05:00"}],
    )
    res = orchestrator.run(order_file, "orders")
    assert res.valid_records == 0
    assert res.quarantined_records == 1
    assert res.published_records == 0
    q_row = orchestrator.storage.fetch_one("SELECT error_message FROM quarantined_records WHERE run_id = $1", [res.run_id])
    assert "does not exist in published_customers" in q_row[0]


# 27. Dedicated FK: Reprocessing customer data & orders after rerun
def test_fk_reprocessing_customer_data(orchestrator: PipelineOrchestrator, tmp_path: Path):
    cust_file = create_csv(
        tmp_path,
        "fk_cust_reprocess.csv",
        [{"customer_id": "CUST-0001", "customer_name": "Alice Initial", "email": "a@ex.com", "city": "NYC", "customer_status": "active", "created_at": "2026-11-01 10:00:00"}],
    )
    res_c1 = orchestrator.run(cust_file, "customers")
    assert res_c1.inserted_records == 1

    # Re-run customer batch with updated name (same CUST-0001)
    cust_file_v2 = create_csv(
        tmp_path,
        "fk_cust_reprocess.csv",
        [{"customer_id": "CUST-0001", "customer_name": "Alice Modified", "email": "a@ex.com", "city": "NYC", "customer_status": "active", "created_at": "2026-11-01 10:00:00"}],
    )
    res_c2 = orchestrator.run(cust_file_v2, "customers")
    assert res_c2.updated_records == 1
    assert orchestrator.storage.fetch_one("SELECT customer_name FROM published_customers WHERE customer_id = 'CUST-0001'")[0] == "Alice Modified"

    # Order referencing CUST-0001 after customer rerun validates cleanly
    order_file = create_csv(
        tmp_path,
        "fk_order_after_rerun.csv",
        [{"order_id": "ORD-00001", "customer_id": "CUST-0001", "order_date": "2026-11-01 11:00:00", "product_name": "Item", "quantity": "1", "unit_price": "10.0", "order_status": "pending", "payment_method": "card", "updated_at": "2026-11-01 11:05:00"}],
    )
    res_o = orchestrator.run(order_file, "orders")
    assert res_o.status == "SUCCESS"
    assert res_o.valid_records == 1


# 28. Quarantine retry with same run_id does not duplicate quarantine entries
def test_quarantine_retry_same_run_id_no_duplicates(orchestrator: PipelineOrchestrator, tmp_path: Path):
    bad_file = create_csv(
        tmp_path,
        "quarantine_idempotent.csv",
        [{"customer_id": "CUST-0001", "customer_name": "Alice", "email": "alice@ex.com", "city": "NYC", "customer_status": "invalid_status", "created_at": "2026-11-01 10:00:00"}],
    )
    # Run with explicit run_id
    res1 = orchestrator.run(bad_file, "customers", run_id="fixed_run_test_001")
    assert res1.quarantined_records == 1
    count1 = orchestrator.storage.fetch_one("SELECT COUNT(*) FROM quarantined_records WHERE run_id = 'fixed_run_test_001'")[0]
    assert count1 == 1

    # Retry with exact same run_id
    res2 = orchestrator.run(bad_file, "customers", run_id="fixed_run_test_001")
    assert res2.quarantined_records == 1
    count2 = orchestrator.storage.fetch_one("SELECT COUNT(*) FROM quarantined_records WHERE run_id = 'fixed_run_test_001'")[0]
    assert count2 == 1  # Did NOT duplicate into 2!

