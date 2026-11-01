"""Comprehensive edge-case test suite for SchemaGuard data platform.

Covers:
1. Large-scale CSV ingestion and publishing (5,000+ records).
2. Cross-batch primary key duplicates and safe upsert semantics.
3. Orders foreign key failure quarantine and subsequent reprocessing workflow.
4. Malformed CSV syntax / parse error handling and failure audit recording.
5. Transactional rollback verification during simulated database failures.
6. Quarantine lineage preservation (source index, raw JSON, batch/run identifiers).
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import pytest

from schemaguard.core.generator import SyntheticDataGenerator
from schemaguard.core.pipeline import PipelineOrchestrator
from schemaguard.core.storage import DuckDBStorageManager


@pytest.fixture
def temp_storage(tmp_path: Path) -> DuckDBStorageManager:
    """Provide an isolated DuckDB storage manager in a temporary folder."""
    db_file = tmp_path / "edge_cases.duckdb"
    return DuckDBStorageManager(db_path=db_file)


@pytest.fixture
def orchestrator(temp_storage: DuckDBStorageManager) -> PipelineOrchestrator:
    """Provide a PipelineOrchestrator instance wired to the isolated temporary storage."""
    return PipelineOrchestrator(storage=temp_storage)


def test_large_csv_ingestion_and_publishing(orchestrator: PipelineOrchestrator, tmp_path: Path):
    """Verify large scale (5,000 records) customer and order generation, ingestion, validation, and publishing."""
    gen = SyntheticDataGenerator(seed=123)
    
    # 1. Generate and ingest 5,000 customers
    cust_df = gen.generate_customers(count=5000)
    cust_csv = tmp_path / "large_customers.csv"
    cust_df.to_csv(cust_csv, index=False)

    cust_res = orchestrator.run(cust_csv, "customers")
    assert cust_res.status == "SUCCESS"
    assert cust_res.total_records == 5000
    assert cust_res.valid_records == 5000
    assert cust_res.quarantined_records == 0
    assert cust_res.published_records == 5000
    assert cust_res.reconciliation_diff == 0

    # 2. Generate and ingest 5,000 orders referencing customers
    order_df = gen.generate_orders(
        count=5000,
        customer_ids=cust_df["customer_id"].tolist(),
    )
    order_csv = tmp_path / "large_orders.csv"
    order_df.to_csv(order_csv, index=False)

    order_res = orchestrator.run(order_csv, "orders")
    assert order_res.status == "SUCCESS"
    assert order_res.total_records == 5000
    assert order_res.valid_records == 5000
    assert order_res.quarantined_records == 0
    assert order_res.published_records == 5000
    assert order_res.reconciliation_diff == 0

    # Verify counts in DuckDB tables
    cust_count = orchestrator.storage.fetch_one("SELECT COUNT(*) FROM published_customers")[0]
    order_count = orchestrator.storage.fetch_one("SELECT COUNT(*) FROM published_orders")[0]
    assert cust_count == 5000
    assert order_count == 5000


def test_cross_batch_duplicates(orchestrator: PipelineOrchestrator, tmp_path: Path):
    """Verify safe upsert semantics across batches with overlapping primary keys."""
    # Batch 1: Customers CUST-0001 to CUST-0005
    batch1_rows = [
        {
            "customer_id": f"CUST-{i:04d}",
            "customer_name": f"User {i}",
            "email": f"user{i}@example.com",
            "city": "NYC",
            "customer_status": "active",
            "created_at": "2026-11-01 10:00:00",
        }
        for i in range(1, 6)
    ]
    b1_csv = tmp_path / "batch1.csv"
    pd.DataFrame(batch1_rows).to_csv(b1_csv, index=False)

    res1 = orchestrator.run(b1_csv, "customers", batch_id="b1")
    assert res1.status == "SUCCESS"
    assert res1.inserted_records == 5
    assert res1.updated_records == 0
    assert res1.published_records == 5

    # Batch 2: Overlapping CUST-0004, CUST-0005 with updated info, plus new CUST-0006, CUST-0007
    batch2_rows = [
        {"customer_id": "CUST-0004", "customer_name": "User Four Updated", "email": "user4.new@example.com", "city": "LA", "customer_status": "active", "created_at": "2026-11-01 10:00:00"},
        {"customer_id": "CUST-0005", "customer_name": "User Five Updated", "email": "user5.new@example.com", "city": "Chicago", "customer_status": "inactive", "created_at": "2026-11-01 10:00:00"},
        {"customer_id": "CUST-0006", "customer_name": "User Six", "email": "user6@example.com", "city": "Austin", "customer_status": "active", "created_at": "2026-11-01 11:00:00"},
        {"customer_id": "CUST-0007", "customer_name": "User Seven", "email": "user7@example.com", "city": "Seattle", "customer_status": "active", "created_at": "2026-11-01 11:00:00"},
    ]
    b2_csv = tmp_path / "batch2.csv"
    pd.DataFrame(batch2_rows).to_csv(b2_csv, index=False)

    res2 = orchestrator.run(b2_csv, "customers", batch_id="b2")
    assert res2.status == "SUCCESS"
    assert res2.inserted_records == 2
    assert res2.updated_records == 2
    assert res2.published_records == 4

    # Total in published table should be 7 (5 original + 2 new, no duplicates!)
    total_custs = orchestrator.storage.fetch_one("SELECT COUNT(*) FROM published_customers")[0]
    assert total_custs == 7

    # Check that update was applied
    updated_name = orchestrator.storage.fetch_one("SELECT customer_name FROM published_customers WHERE customer_id = 'CUST-0004'")[0]
    assert updated_name == "User Four Updated"


def test_orders_reprocessing_workflow(orchestrator: PipelineOrchestrator, tmp_path: Path):
    """Verify that an order with a missing FK is quarantined initially, and successfully publishes when reprocessed after FK is satisfied."""
    order_rows = [
        {
            "order_id": "ORD-00001",
            "customer_id": "CUST-9999",
            "order_date": "2026-11-01",
            "product_name": "Laptop Stand",
            "quantity": 1,
            "unit_price": 49.99,
            "order_status": "pending",
            "payment_method": "card",
            "updated_at": "2026-11-01 12:00:00",
        }
    ]
    order_csv = tmp_path / "orphan_order.csv"
    pd.DataFrame(order_rows).to_csv(order_csv, index=False)

    # 1. Attempt initial order run before customer exists
    res1 = orchestrator.run(order_csv, "orders", batch_id="order_b1")
    assert res1.status == "PARTIAL_SUCCESS"
    assert res1.total_records == 1
    assert res1.valid_records == 0
    assert res1.quarantined_records == 1
    assert res1.published_records == 0

    # Verify quarantine table has record
    quarantine_rows = orchestrator.storage.fetch_all("SELECT violation_field, violation_rule FROM quarantined_records WHERE source_record_id = 'ORD-00001'")
    assert len(quarantine_rows) == 1
    assert quarantine_rows[0][0] == "customer_id"
    assert "foreign_key" in quarantine_rows[0][1].lower()

    # 2. Ingest parent customer
    cust_rows = [
        {
            "customer_id": "CUST-9999",
            "customer_name": "Future Customer",
            "email": "future@example.com",
            "city": "Denver",
            "customer_status": "active",
            "created_at": "2026-11-01 12:30:00",
        }
    ]
    cust_csv = tmp_path / "parent_cust.csv"
    pd.DataFrame(cust_rows).to_csv(cust_csv, index=False)
    cust_res = orchestrator.run(cust_csv, "customers")
    assert cust_res.status == "SUCCESS"

    # 3. Reprocess the original orders file
    res2 = orchestrator.run(order_csv, "orders", batch_id="order_b1_retry")
    assert res2.status == "SUCCESS"
    assert res2.valid_records == 1
    assert res2.quarantined_records == 0
    assert res2.published_records == 1

    # Verify published order exists
    order_in_db = orchestrator.storage.fetch_one("SELECT order_id, total_amount FROM published_orders WHERE order_id = 'ORD-00001'")
    assert order_in_db is not None
    assert order_in_db[0] == "ORD-00001"
    assert pytest.approx(order_in_db[1], 0.01) == 49.99


def test_malformed_csv_handling(orchestrator: PipelineOrchestrator, tmp_path: Path):
    """Verify that a malformed / corrupted CSV triggers an ingestion error and is recorded in pipeline_runs."""
    bad_csv = tmp_path / "corrupt_syntax.csv"
    # Write invalid content: unclosed quote spanning unexpected tokens
    with open(bad_csv, "w", encoding="utf-8") as f:
        f.write('customer_id,customer_name,email,city,customer_status,created_at\n')
        f.write('CUST-0001,"Alice Smith,alice@test.com,NYC,active,2026-11-01 10:00:00\n')
        f.write('CUST-0002,Bob,"bob@test.com,SF,active,2026-11-01 10:00:00\n')
        f.write('"Broken quote without closing delimiter\x00\xff\n')

    res = orchestrator.run(bad_csv, "customers")
    # Ingestor should either gracefully quarantine or fail with recorded status FAILED
    assert res.status in ["FAILED", "QUARANTINED"]
    assert res.published_records == 0

    # Ensure run was recorded in DuckDB audit log
    runs = orchestrator.storage.fetch_all("SELECT run_id, status, error_summary FROM pipeline_runs WHERE source_file = 'corrupt_syntax.csv'")
    assert len(runs) >= 1
    assert runs[0][1] in ["FAILED", "QUARANTINED"]


def test_failed_transactional_rollback(orchestrator: PipelineOrchestrator, tmp_path: Path):
    """Verify transactional atomicity and rollback: mid-transaction crash results in zero dirty rows committed."""
    cust_rows = [
        {"customer_id": "CUST-9991", "customer_name": "Rollback User", "email": "rollback@example.com", "city": "Dallas", "customer_status": "active", "created_at": "2026-11-01 10:00:00"}
    ]
    csv_file = tmp_path / "rollback_test.csv"
    pd.DataFrame(cust_rows).to_csv(csv_file, index=False)

    # Patch upsert_published_records to simulate an unexpected database crash mid-transaction
    with patch.object(orchestrator.storage, "upsert_published_records", side_effect=RuntimeError("Simulated DuckDB disk I/O failure")):
        with pytest.raises(RuntimeError, match="Simulated DuckDB disk I/O failure"):
            orchestrator.run(csv_file, "customers")

    # Ensure run was recorded as FAILED in pipeline_runs
    runs = orchestrator.storage.fetch_all("SELECT status, error_summary FROM pipeline_runs WHERE source_file = 'rollback_test.csv'")
    assert len(runs) >= 1
    assert runs[0][0] == "FAILED"
    assert "Database publish transaction failed and was rolled back" in runs[0][1]

    # Published customers table must NOT contain the row
    rows = orchestrator.storage.fetch_all("SELECT * FROM published_customers WHERE customer_id = 'CUST-9991'")
    assert len(rows) == 0


def test_quarantine_lineage_preservation(orchestrator: PipelineOrchestrator, tmp_path: Path):
    """Verify that quarantined records preserve accurate lineage (source record index, raw JSON payload, file name, run_id)."""
    rows = [
        # Row index 0: valid
        {"customer_id": "CUST-1001", "customer_name": "Valid Lineage", "email": "valid@example.com", "city": "Austin", "customer_status": "active", "created_at": "2026-11-01 10:00:00"},
        # Row index 1: invalid customer_status and invalid email
        {"customer_id": "CUST-1002", "customer_name": "Invalid Lineage", "email": "not-an-email", "city": "Austin", "customer_status": "unknown_status", "created_at": "2026-11-01 10:00:00"},
    ]
    csv_file = tmp_path / "lineage_test.csv"
    pd.DataFrame(rows).to_csv(csv_file, index=False)

    res = orchestrator.run(csv_file, "customers", batch_id="batch_lin_01")
    assert res.total_records == 2
    assert res.valid_records == 1
    assert res.quarantined_records == 1

    # Fetch quarantine record from DuckDB
    q_rows = orchestrator.storage.fetch_all(
        "SELECT source_record_id, row_index, source_file, batch_id, raw_record, violation_field "
        "FROM quarantined_records WHERE source_record_id = 'CUST-1002'"
    )
    assert len(q_rows) >= 1
    record_id, source_idx, source_file, batch_id, raw_record_json, violation_field = q_rows[0]

    assert record_id == "CUST-1002"
    assert source_idx == 1  # 0-indexed row position
    assert source_file == "lineage_test.csv"
    assert batch_id == "batch_lin_01"

    # Verify JSON deserialization preserves the exact raw row
    raw_dict = json.loads(raw_record_json)
    assert raw_dict["customer_name"] == "Invalid Lineage"
    assert raw_dict["email"] == "not-an-email"
    assert raw_dict["customer_status"] == "unknown_status"
