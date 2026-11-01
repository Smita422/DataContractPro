"""Integration tests for SchemaGuard FastAPI REST API Service."""

from pathlib import Path
from typing import Any, Dict, List
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from schemaguard.api.dependencies import get_storage
from schemaguard.api.main import app
from schemaguard.core.storage import DuckDBStorageManager


def create_csv(tmp_path: Path, filename: str, rows: List[Dict[str, Any]]) -> Path:
    """Helper to generate a temporary CSV file with test data."""
    csv_path = tmp_path / filename
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    return csv_path


@pytest.fixture
def client(tmp_path: Path):
    """Fixture providing an isolated FastAPI TestClient with a fresh DuckDB database."""
    test_db = tmp_path / "test_api.duckdb"
    test_storage = DuckDBStorageManager(db_path=test_db)

    # Override dependency to use isolated test database
    app.dependency_overrides[get_storage] = lambda: test_storage

    with TestClient(app) as test_client:
        yield test_client, test_storage

    # Clean up overrides
    app.dependency_overrides.clear()


# ==============================================================================
# 1. Health Endpoint
# ==============================================================================

def test_health_endpoint(client):
    test_client, _ = client
    response = test_client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"
    assert data["version"] == "0.1.0"
    assert "timestamp" in data


# ==============================================================================
# 2. Database Connectivity Failure Handling
# ==============================================================================

def test_database_connectivity_failure(client, monkeypatch):
    test_client, test_storage = client

    def broken_fetch_one(*args, **kwargs):
        raise RuntimeError("Simulated DB connection failure")

    monkeypatch.setattr(test_storage, "fetch_one", broken_fetch_one)
    response = test_client.get("/api/v1/health")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["database"] == "disconnected"


# ==============================================================================
# 3. List Contracts
# ==============================================================================

def test_list_contracts(client):
    test_client, _ = client
    response = test_client.get("/api/v1/contracts")
    assert response.status_code == 200
    data = response.json()
    assert "datasets" in data
    assert "customers" in data["datasets"]
    assert "orders" in data["datasets"]
    assert "1.0.0" in data["datasets"]["customers"]
    assert "1.0.0" in data["datasets"]["orders"]
    assert "1.1.0" in data["datasets"]["orders"]
    assert data["total_datasets"] >= 2


# ==============================================================================
# 4. Retrieve Customer Contract
# ==============================================================================

def test_retrieve_customer_contract(client):
    test_client, _ = client
    response = test_client.get("/api/v1/contracts/customers")
    assert response.status_code == 200
    data = response.json()
    assert data["dataset"] == "customers"
    assert data["version"] == "1.0.0"
    assert data["compatibility_mode"] == "BACKWARD"

    column_names = [col["name"] for col in data["columns"]]
    assert "customer_id" in column_names
    assert "customer_name" in column_names
    assert "email" in column_names
    assert "city" in column_names
    assert "customer_status" in column_names
    assert "created_at" in column_names

    # Verify primary key and constraints
    cust_id_col = next(c for c in data["columns"] if c["name"] == "customer_id")
    assert cust_id_col["primary_key"] is True
    assert cust_id_col["nullable"] is False


# ==============================================================================
# 5. Retrieve Order Contract
# ==============================================================================

def test_retrieve_order_contract(client):
    test_client, _ = client
    response = test_client.get("/api/v1/contracts/orders?version=1.1.0")
    assert response.status_code == 200
    data = response.json()
    assert data["dataset"] == "orders"
    assert data["version"] == "1.1.0"

    col_names = [col["name"] for col in data["columns"]]
    assert "order_id" in col_names
    assert "delivery_status" in col_names  # v1.1.0 optional column

    # Verify derived fields
    assert len(data["derived_fields"]) == 1
    derived = data["derived_fields"][0]
    assert derived["name"] == "total_amount"
    assert derived["expression"] == "quantity * unit_price"


# ==============================================================================
# 6. Invalid Dataset
# ==============================================================================

def test_invalid_dataset(client):
    test_client, _ = client
    response = test_client.get("/api/v1/contracts/non_existent_dataset")
    assert response.status_code == 404
    assert "no contracts directory found" in response.json()["detail"].lower()


# ==============================================================================
# 7. Submit Valid Customer Batch
# ==============================================================================

def test_submit_valid_customer_batch(client, tmp_path):
    test_client, _ = client
    csv_file = create_csv(
        tmp_path,
        "customers_valid.csv",
        [{
            "customer_id": "CUST-0001",
            "customer_name": "Alice Green",
            "email": "alice@example.com",
            "city": "Austin",
            "customer_status": "active",
            "created_at": "2026-11-01 10:00:00",
        }],
    )

    payload = {
        "dataset": "customers",
        "file_path": str(csv_file),
        "contract_version": "1.0.0",
        "schema_mode": "PERMISSIVE",
    }
    response = test_client.post("/api/v1/pipeline/runs", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert data["total_records"] == 1
    assert data["valid_records"] == 1
    assert data["quarantined_records"] == 0
    assert data["published_records"] == 1
    assert data["inserted_records"] == 1
    assert data["updated_records"] == 0
    assert data["reconciliation_diff"] == 0
    assert data["reconciliation_status"] == "BALANCED (diff=0)"


# ==============================================================================
# 8. Submit Valid Order Batch
# ==============================================================================

def test_submit_valid_order_batch(client, tmp_path):
    test_client, _ = client

    # Pre-publish customer
    cust_file = create_csv(
        tmp_path,
        "cust_prep.csv",
        [{
            "customer_id": "CUST-0001",
            "customer_name": "Alice Green",
            "email": "alice@example.com",
            "city": "Austin",
            "customer_status": "active",
            "created_at": "2026-11-01 10:00:00",
        }],
    )
    test_client.post("/api/v1/pipeline/runs", json={"dataset": "customers", "file_path": str(cust_file)})

    # Submit order batch referencing published customer
    order_file = create_csv(
        tmp_path,
        "orders_valid.csv",
        [{
            "order_id": "ORD-00001",
            "customer_id": "CUST-0001",
            "order_date": "2026-11-01 11:00:00",
            "product_name": "Keyboard",
            "quantity": 2,
            "unit_price": 75.0,
            "order_status": "delivered",
            "payment_method": "card",
            "updated_at": "2026-11-01 11:05:00",
        }],
    )
    response = test_client.post(
        "/api/v1/pipeline/runs",
        json={"dataset": "orders", "file_path": str(order_file), "contract_version": "1.0.0"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert data["published_records"] == 1
    assert data["reconciliation_diff"] == 0


# ==============================================================================
# 9. Missing Input File
# ==============================================================================

def test_missing_input_file(client, tmp_path):
    test_client, _ = client
    non_existent = tmp_path / "does_not_exist.csv"

    response = test_client.post(
        "/api/v1/pipeline/runs",
        json={"dataset": "customers", "file_path": str(non_existent)},
    )
    assert response.status_code == 404
    assert "Input file not found" in response.json()["detail"]


# ==============================================================================
# 10. Invalid Contract Version
# ==============================================================================

def test_invalid_contract_version(client, tmp_path):
    test_client, _ = client
    dummy_csv = create_csv(tmp_path, "dummy.csv", [{"customer_id": "C1"}])

    response = test_client.post(
        "/api/v1/pipeline/runs",
        json={"dataset": "customers", "file_path": str(dummy_csv), "contract_version": "99.99.99"},
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


# ==============================================================================
# 11. Invalid Request Body
# ==============================================================================

def test_invalid_request_body(client):
    test_client, _ = client
    # Missing file_path
    response = test_client.post("/api/v1/pipeline/runs", json={"dataset": "customers"})
    assert response.status_code == 422
    assert "Request validation failed" in response.json()["detail"]


# ==============================================================================
# 12. Pipeline Partial Success
# ==============================================================================

def test_pipeline_partial_success(client, tmp_path):
    test_client, _ = client
    csv_file = create_csv(
        tmp_path,
        "customers_mixed.csv",
        [
            # Valid row
            {
                "customer_id": "CUST-0001",
                "customer_name": "Alice Green",
                "email": "alice@example.com",
                "city": "Austin",
                "customer_status": "active",
                "created_at": "2026-11-01 10:00:00",
            },
            # Corrupt row (invalid email)
            {
                "customer_id": "CUST-0002",
                "customer_name": "Bob Blue",
                "email": "invalid-email-address",
                "city": "Boston",
                "customer_status": "active",
                "created_at": "2026-11-01 10:00:00",
            },
        ],
    )
    response = test_client.post(
        "/api/v1/pipeline/runs",
        json={"dataset": "customers", "file_path": str(csv_file)},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "PARTIAL_SUCCESS"
    assert data["total_records"] == 2
    assert data["valid_records"] == 1
    assert data["quarantined_records"] == 1
    assert data["published_records"] == 1
    assert data["reconciliation_diff"] == 0


# ==============================================================================
# 13. Retrieve Run History
# ==============================================================================

def test_retrieve_run_history(client, tmp_path):
    test_client, _ = client
    csv_file = create_csv(
        tmp_path,
        "cust_hist.csv",
        [{
            "customer_id": "CUST-0001",
            "customer_name": "Alice",
            "email": "a@ex.com",
            "city": "NYC",
            "customer_status": "active",
            "created_at": "2026-11-01 10:00:00",
        }],
    )
    test_client.post("/api/v1/pipeline/runs", json={"dataset": "customers", "file_path": str(csv_file)})

    response = test_client.get("/api/v1/runs?limit=10&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert len(data["items"]) >= 1
    run = data["items"][0]
    assert run["dataset_name"] == "customers"
    assert run["status"] == "SUCCESS"


# ==============================================================================
# 14. Retrieve Run by ID
# ==============================================================================

def test_retrieve_run_by_id(client, tmp_path):
    test_client, _ = client
    csv_file = create_csv(
        tmp_path,
        "cust_by_id.csv",
        [{
            "customer_id": "CUST-0001",
            "customer_name": "Alice",
            "email": "a@ex.com",
            "city": "NYC",
            "customer_status": "active",
            "created_at": "2026-11-01 10:00:00",
        }],
    )
    run_resp = test_client.post("/api/v1/pipeline/runs", json={"dataset": "customers", "file_path": str(csv_file)})
    run_id = run_resp.json()["run_id"]

    response = test_client.get(f"/api/v1/runs/{run_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == run_id
    assert data["dataset_name"] == "customers"
    assert data["total_records"] == 1


# ==============================================================================
# 15. Unknown Run ID
# ==============================================================================

def test_unknown_run_id(client):
    test_client, _ = client
    response = test_client.get("/api/v1/runs/run_does_not_exist_999999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


# ==============================================================================
# 16. Retrieve Quarantine Records
# ==============================================================================

def test_retrieve_quarantine_records(client, tmp_path):
    test_client, _ = client
    bad_csv = create_csv(
        tmp_path,
        "cust_bad_email.csv",
        [{
            "customer_id": "CUST-9999",
            "customer_name": "Corrupt",
            "email": "not-an-email",
            "city": "Miami",
            "customer_status": "active",
            "created_at": "2026-11-01 10:00:00",
        }],
    )
    test_client.post("/api/v1/pipeline/runs", json={"dataset": "customers", "file_path": str(bad_csv)})

    response = test_client.get("/api/v1/quarantine?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert len(data["items"]) >= 1
    item = data["items"][0]
    assert item["violation_field"] == "email"


# ==============================================================================
# 17. Filter Quarantine Records
# ==============================================================================

def test_filter_quarantine_records(client, tmp_path):
    test_client, _ = client
    bad_csv = create_csv(
        tmp_path,
        "cust_filter.csv",
        [{
            "customer_id": "CUST-9999",
            "customer_name": "Corrupt",
            "email": "not-an-email",
            "city": "Miami",
            "customer_status": "active",
            "created_at": "2026-11-01 10:00:00",
        }],
    )
    post_res = test_client.post("/api/v1/pipeline/runs", json={"dataset": "customers", "file_path": str(bad_csv)})
    run_id = post_res.json()["run_id"]

    # Filter by run_id and dataset
    response = test_client.get(f"/api/v1/quarantine?run_id={run_id}&dataset=customers")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["run_id"] == run_id


# ==============================================================================
# 18. Retrieve Quarantine Record Details
# ==============================================================================

def test_retrieve_quarantine_record_details(client, tmp_path):
    test_client, _ = client
    bad_csv = create_csv(
        tmp_path,
        "cust_detail.csv",
        [{
            "customer_id": "CUST-8888",
            "customer_name": "Broken Record",
            "email": "not-valid",
            "city": "Dallas",
            "customer_status": "active",
            "created_at": "2026-11-01 10:00:00",
        }],
    )
    test_client.post("/api/v1/pipeline/runs", json={"dataset": "customers", "file_path": str(bad_csv)})

    list_res = test_client.get("/api/v1/quarantine?limit=1")
    q_id = list_res.json()["items"][0]["quarantine_id"]

    response = test_client.get(f"/api/v1/quarantine/{q_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["quarantine_id"] == q_id
    assert "raw_record" in data
    assert data["raw_record"]["customer_id"] == "CUST-8888"
    assert data["violation_field"] == "email"


# ==============================================================================
# 19. Metrics Summary
# ==============================================================================

def test_metrics_summary(client, tmp_path):
    test_client, _ = client

    # Empty initially
    res_empty = test_client.get("/api/v1/metrics/summary")
    assert res_empty.status_code == 200
    assert res_empty.json()["total_runs"] == 0

    # Ingest 1 customer file
    csv_file = create_csv(
        tmp_path,
        "cust_metrics.csv",
        [{
            "customer_id": "CUST-0001",
            "customer_name": "Alice",
            "email": "a@ex.com",
            "city": "NYC",
            "customer_status": "active",
            "created_at": "2026-11-01 10:00:00",
        }],
    )
    test_client.post("/api/v1/pipeline/runs", json={"dataset": "customers", "file_path": str(csv_file)})

    response = test_client.get("/api/v1/metrics/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["total_runs"] == 1
    assert data["successful_runs"] == 1
    assert data["total_input_records"] == 1
    assert data["total_published_records"] == 1
    assert len(data["datasets"]) == 1
    assert data["datasets"][0]["dataset_name"] == "customers"


# ==============================================================================
# 20. Repeated API Execution and Idempotency
# ==============================================================================

def test_repeated_api_execution_idempotency(client, tmp_path):
    test_client, test_storage = client
    csv_file = create_csv(
        tmp_path,
        "cust_idem.csv",
        [{
            "customer_id": "CUST-0001",
            "customer_name": "Alice Green",
            "email": "alice@example.com",
            "city": "Austin",
            "customer_status": "active",
            "created_at": "2026-11-01 10:00:00",
        }],
    )
    payload = {"dataset": "customers", "file_path": str(csv_file)}

    # Run 1
    res1 = test_client.post("/api/v1/pipeline/runs", json=payload)
    assert res1.status_code == 201
    d1 = res1.json()
    assert d1["inserted_records"] == 1
    assert d1["updated_records"] == 0

    # Run 2 (exact same file)
    res2 = test_client.post("/api/v1/pipeline/runs", json=payload)
    assert res2.status_code == 201
    d2 = res2.json()
    assert d2["batch_id"] == d1["batch_id"]      # Identical batch_id
    assert d2["run_id"] != d1["run_id"]          # Distinct run_id
    assert d2["inserted_records"] == 0          # 0 new rows
    assert d2["updated_records"] == 1           # 1 updated

    # Total row count in DuckDB table remains exactly 1
    count = test_storage.fetch_one("SELECT COUNT(*) FROM published_customers")[0]
    assert count == 1


# ==============================================================================
# 21. Breaking Schema Rejection
# ==============================================================================

def test_breaking_schema_rejection(client, tmp_path):
    test_client, _ = client
    # Customer batch with extra unexpected column under STRICT mode
    csv_file = create_csv(
        tmp_path,
        "cust_strict_breach.csv",
        [{
            "customer_id": "CUST-0001",
            "customer_name": "Alice",
            "email": "a@ex.com",
            "city": "NYC",
            "customer_status": "active",
            "created_at": "2026-11-01 10:00:00",
            "unauthorized_field": "breach_payload",
        }],
    )
    payload = {
        "dataset": "customers",
        "file_path": str(csv_file),
        "schema_mode": "STRICT",
    }
    response = test_client.post("/api/v1/pipeline/runs", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "SCHEMA_REJECTED"
    assert data["published_records"] == 0
    assert len(data["schema_changes"]) >= 1


# ==============================================================================
# 22. API Security and Error Handling
# ==============================================================================

def test_api_security_path_traversal(client):
    test_client, _ = client
    # Forbidden path traversal outside allowed data directories
    payload = {
        "dataset": "customers",
        "file_path": "../../../../../../../../../Windows/System32/drivers/etc/hosts",
    }
    response = test_client.post("/api/v1/pipeline/runs", json=payload)
    assert response.status_code == 400
    assert "restricted" in response.json()["detail"].lower()


def test_root_endpoint(client):
    test_client, _ = client
    response = test_client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "SchemaGuard API"
    assert "/docs" in data["docs_url"]


# ==============================================================================
# 23. Schema Evolution Events Endpoint
# ==============================================================================

def test_list_evolution_events(client, tmp_path):
    test_client, _ = client
    # Trigger run with extra column
    csv_file = create_csv(
        tmp_path,
        "cust_evol_test.csv",
        [{
            "customer_id": "CUST-0001",
            "customer_name": "Alice",
            "email": "a@ex.com",
            "city": "NYC",
            "customer_status": "active",
            "created_at": "2026-11-01 10:00:00",
            "unauthorized_field": "breach_payload",
        }],
    )
    test_client.post("/api/v1/pipeline/runs", json={"dataset": "customers", "file_path": str(csv_file), "schema_mode": "STRICT"})

    response = test_client.get("/api/v1/evolution/events")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    item = data["items"][0]
    assert item["dataset_name"] == "customers"
    assert item["is_breaking"] is True
    assert item["impact"] == "BREAKING"

