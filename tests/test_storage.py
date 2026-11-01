"""Unit tests for DuckDB storage initialization, transactions, and metadata management."""

from datetime import datetime
import pandas as pd
import pytest
from schemaguard.core.storage import DuckDBStorageManager


def test_schema_initialization(in_memory_storage: DuckDBStorageManager):
    """Verify that all required metadata and domain tables are created on initialization."""
    tables = in_memory_storage.fetch_all(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    )
    table_names = {row[0] for row in tables}

    expected_tables = {
        "data_contracts",
        "pipeline_runs",
        "schema_evolution_events",
        "quarantined_records",
        "published_customers",
        "published_orders",
    }
    assert expected_tables.issubset(table_names), (
        f"Missing tables: {expected_tables - table_names}"
    )


def test_transaction_rollback(in_memory_storage: DuckDBStorageManager):
    """Verify that an exception inside a transaction cleanly rolls back all modifications."""
    # Ensure starting count is 0
    initial_count = in_memory_storage.fetch_one(
        "SELECT COUNT(*) FROM published_customers"
    )[0]
    assert initial_count == 0

    # Execute a transaction that deliberately fails
    with pytest.raises(RuntimeError, match="Simulated pipeline failure"):
        with in_memory_storage.transaction() as tx_con:
            tx_con.execute(
                """
                INSERT INTO published_customers (
                    customer_id, customer_name, email, city, customer_status,
                    created_at, _sg_batch_id, _sg_run_id, _sg_source_file, _sg_loaded_at
                ) VALUES (
                    'CUST-0001', 'Alice Test', 'alice@test.com', 'New York', 'ACTIVE',
                    CURRENT_TIMESTAMP, 'batch-1', 'run-1', 'test.csv', CURRENT_TIMESTAMP
                )
                """
            )
            # Deliberately raise exception before commit
            raise RuntimeError("Simulated pipeline failure")

    # Confirm that row was NOT committed
    after_rollback_count = in_memory_storage.fetch_one(
        "SELECT COUNT(*) FROM published_customers"
    )[0]
    assert after_rollback_count == 0


def test_pipeline_run_upsert(in_memory_storage: DuckDBStorageManager):
    """Verify recording and idempotent updating of pipeline execution runs."""
    start_time = datetime(2026, 11, 1, 10, 0, 0)
    run_data = {
        "run_id": "run-001",
        "batch_id": "batch-100",
        "batch_fingerprint": "abc123hash",
        "dataset_name": "orders",
        "contract_version": "1.0.0",
        "status": "RUNNING",
        "total_records": 100,
        "valid_records": 0,
        "quarantined_records": 0,
        "reconciliation_diff": 0,
        "start_time": start_time,
        "source_file": "orders_batch_1.csv",
        "error_summary": None,
    }

    in_memory_storage.record_pipeline_run(run_data)

    row = in_memory_storage.fetch_one(
        "SELECT status, total_records FROM pipeline_runs WHERE run_id = 'run-001'"
    )
    assert row == ("RUNNING", 100)

    # Update run status upon completion
    run_data.update({
        "status": "PARTIAL_SUCCESS",
        "valid_records": 95,
        "quarantined_records": 5,
        "reconciliation_diff": 0,
        "end_time": datetime(2026, 11, 1, 10, 0, 2),
        "duration_ms": 2000,
        "error_summary": "5 records quarantined due to null checks",
    })
    in_memory_storage.record_pipeline_run(run_data)

    updated_row = in_memory_storage.fetch_one(
        "SELECT status, valid_records, quarantined_records, duration_ms FROM pipeline_runs WHERE run_id = 'run-001'"
    )
    assert updated_row == ("PARTIAL_SUCCESS", 95, 5, 2000)


def test_schema_evolution_logging(in_memory_storage: DuckDBStorageManager):
    """Verify logging of schema evolution events."""
    event = {
        "event_id": "evt-001",
        "run_id": "run-001",
        "batch_id": "batch-100",
        "dataset_name": "orders",
        "contract_version": "1.1.0",
        "change_type": "COLUMN_ADDED",
        "is_breaking": False,
        "column_name": "discount_rate",
        "diff_details": "New optional column 'discount_rate' detected in batch",
    }
    in_memory_storage.log_schema_evolution(event)

    row = in_memory_storage.fetch_one(
        "SELECT change_type, is_breaking, column_name FROM schema_evolution_events WHERE event_id = 'evt-001'"
    )
    assert row == ("COLUMN_ADDED", False, "discount_rate")


def test_quarantine_records_insertion(in_memory_storage: DuckDBStorageManager):
    """Verify inserting quarantined rows and querying violation diagnostics."""
    records = [
        {
            "quarantine_id": "q-001",
            "run_id": "run-001",
            "batch_id": "batch-100",
            "dataset_name": "orders",
            "row_index": 4,
            "raw_record": '{"order_id": "ORD-99999", "quantity": -2}',
            "violation_field": "quantity",
            "violation_rule": "min: 1",
            "error_message": "Quantity cannot be less than 1",
            "source_file": "orders.csv",
        }
    ]
    in_memory_storage.insert_quarantine_records(records)

    row = in_memory_storage.fetch_one(
        "SELECT violation_field, violation_rule FROM quarantined_records WHERE quarantine_id = 'q-001'"
    )
    assert row == ("quantity", "min: 1")


def test_published_records_idempotent_upsert(in_memory_storage: DuckDBStorageManager):
    """Verify safe upsert logic: deduplicates on PK and updates changed fields without multiplying rows."""
    now = pd.Timestamp.now()
    initial_data = pd.DataFrame([
        {
            "customer_id": "CUST-0001",
            "customer_name": "Bob Original",
            "email": "bob@example.com",
            "city": "Boston",
            "customer_status": "PENDING",
            "created_at": now,
            "_sg_batch_id": "batch-01",
            "_sg_run_id": "run-01",
            "_sg_source_file": "cust.csv",
            "_sg_loaded_at": now,
        },
        {
            "customer_id": "CUST-0002",
            "customer_name": "Charlie Clean",
            "email": "charlie@example.com",
            "city": "Chicago",
            "customer_status": "ACTIVE",
            "created_at": now,
            "_sg_batch_id": "batch-01",
            "_sg_run_id": "run-01",
            "_sg_source_file": "cust.csv",
            "_sg_loaded_at": now,
        },
    ])

    # Initial load
    count1 = in_memory_storage.upsert_published_records("customers", initial_data, primary_key="customer_id")
    assert count1 == 2
    assert in_memory_storage.fetch_one("SELECT COUNT(*) FROM published_customers")[0] == 2

    # Second batch updates CUST-0001 from PENDING to ACTIVE, and adds CUST-0003
    updated_data = pd.DataFrame([
        {
            "customer_id": "CUST-0001",
            "customer_name": "Bob Updated",
            "email": "bob@example.com",
            "city": "Boston",
            "customer_status": "ACTIVE",
            "created_at": now,
            "_sg_batch_id": "batch-02",
            "_sg_run_id": "run-02",
            "_sg_source_file": "cust_v2.csv",
            "_sg_loaded_at": now,
        },
        {
            "customer_id": "CUST-0003",
            "customer_name": "Diana New",
            "email": "diana@example.com",
            "city": "Denver",
            "customer_status": "ACTIVE",
            "created_at": now,
            "_sg_batch_id": "batch-02",
            "_sg_run_id": "run-02",
            "_sg_source_file": "cust_v2.csv",
            "_sg_loaded_at": now,
        },
    ])

    count2 = in_memory_storage.upsert_published_records("customers", updated_data, primary_key="customer_id")
    assert count2 == 2

    # Total row count should now be 3 (not 4)
    total_rows = in_memory_storage.fetch_one("SELECT COUNT(*) FROM published_customers")[0]
    assert total_rows == 3

    # Verify CUST-0001 status was updated to ACTIVE and name to Bob Updated
    cust_1 = in_memory_storage.fetch_one(
        "SELECT customer_name, customer_status, _sg_batch_id FROM published_customers WHERE customer_id = 'CUST-0001'"
    )
    assert cust_1 == ("Bob Updated", "ACTIVE", "batch-02")
