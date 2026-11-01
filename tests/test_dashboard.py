"""Unit and integration tests for SchemaGuard Dashboard and API Client."""

from unittest.mock import MagicMock, patch
import httpx
import pytest

from schemaguard.dashboard.api_client import SchemaGuardAPIClient
from schemaguard.dashboard.components.kpi_cards import calculate_data_quality_pct
from schemaguard.dashboard.views.execution import get_available_data_files


# ==============================================================================
# 1. Dashboard Imports Test
# ==============================================================================

def test_dashboard_imports():
    """Verify that all dashboard modules, views, and components import cleanly."""
    import schemaguard.dashboard.app as app_mod
    import schemaguard.dashboard.api_client as client_mod
    import schemaguard.dashboard.components.sidebar as sidebar_mod
    import schemaguard.dashboard.components.kpi_cards as kpi_mod
    import schemaguard.dashboard.components.charts as charts_mod
    import schemaguard.dashboard.components.tables as tables_mod
    import schemaguard.dashboard.views.overview as ov_mod
    import schemaguard.dashboard.views.pipeline_runs as runs_mod
    import schemaguard.dashboard.views.schema_evolution as evol_mod
    import schemaguard.dashboard.views.quarantine as quar_mod
    import schemaguard.dashboard.views.contracts as cont_mod
    import schemaguard.dashboard.views.execution as exec_mod

    assert app_mod is not None
    assert client_mod.SchemaGuardAPIClient is not None


# ==============================================================================
# 2. KPI Quality Percentage Calculation Formula Tests
# ==============================================================================

def test_kpi_quality_percentage_calculation():
    """Verify data quality percentage mathematical calculation and edge cases."""
    # Standard 95% quality
    assert calculate_data_quality_pct(published_records=95, input_records=100) == 95.0

    # Perfect quality
    assert calculate_data_quality_pct(published_records=50, input_records=50) == 100.0

    # Complete rejection (0% quality)
    assert calculate_data_quality_pct(published_records=0, input_records=50) == 0.0

    # Safe zero-input handling (returns None for N/A display, prevents ZeroDivisionError)
    assert calculate_data_quality_pct(published_records=0, input_records=0) is None

    # Floating point precision rounding
    assert calculate_data_quality_pct(published_records=5, input_records=6) == 83.33

    # Negative bounds safety
    assert calculate_data_quality_pct(published_records=-5, input_records=10) == 0.0


# ==============================================================================
# 3. API Client Health Check Tests
# ==============================================================================

def test_api_client_health_success():
    """Test health check parsing on successful 200 response."""
    client = SchemaGuardAPIClient(base_url="http://testbackend:8000")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "healthy",
        "database": "connected",
        "version": "0.1.0",
    }

    with patch.object(httpx.Client, "get", return_value=mock_resp):
        health = client.check_health()
        assert health["is_available"] is True
        assert health["status"] == "healthy"
        assert health["database"] == "connected"


def test_api_client_health_connection_failure():
    """Test health check graceful fallback when server is unreachable."""
    client = SchemaGuardAPIClient(base_url="http://offline-backend:9999")

    with patch.object(httpx.Client, "get", side_effect=httpx.ConnectError("Connection refused")):
        health = client.check_health()
        assert health["is_available"] is False
        assert health["status"] == "unavailable"
        assert health["database"] == "unreachable"
        assert "Connection refused" in health["detail"]


# ==============================================================================
# 4. API Client Metrics Summary Tests
# ==============================================================================

def test_api_client_metrics_summary_success():
    """Test metrics summary retrieval and parsing."""
    client = SchemaGuardAPIClient()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "total_runs": 10,
        "successful_runs": 8,
        "partial_success_runs": 2,
        "failed_runs": 0,
        "schema_rejected_runs": 0,
        "total_input_records": 1000,
        "total_published_records": 980,
        "total_rejected_records": 20,
        "datasets": [{"dataset_name": "customers", "total_runs": 5}],
    }

    with patch.object(httpx.Client, "get", return_value=mock_resp):
        metrics = client.get_metrics_summary()
        assert metrics["total_runs"] == 10
        assert metrics["total_published_records"] == 980
        assert len(metrics["datasets"]) == 1


def test_api_client_metrics_summary_failure():
    """Test metrics summary graceful fallback on HTTP error."""
    client = SchemaGuardAPIClient()

    with patch.object(httpx.Client, "get", side_effect=httpx.HTTPError("Server 500 error")):
        metrics = client.get_metrics_summary()
        assert "error" in metrics
        assert metrics["total_runs"] == 0
        assert metrics["total_published_records"] == 0


# ==============================================================================
# 5. API Client Contracts Discovery Tests
# ==============================================================================

def test_api_client_contracts_discovery():
    """Test contracts listing and specific contract retrieval."""
    client = SchemaGuardAPIClient()

    # List contracts
    mock_list = MagicMock()
    mock_list.status_code = 200
    mock_list.json.return_value = {
        "datasets": {"customers": ["1.0.0"], "orders": ["1.0.0", "1.1.0"]},
        "total_datasets": 2,
    }

    with patch.object(httpx.Client, "get", return_value=mock_list):
        contracts = client.list_contracts()
        assert "customers" in contracts["datasets"]
        assert contracts["total_datasets"] == 2

    # Get single contract
    mock_single = MagicMock()
    mock_single.status_code = 200
    mock_single.json.return_value = {
        "dataset": "customers",
        "version": "1.0.0",
        "columns": [{"name": "customer_id", "type": "string"}],
    }

    with patch.object(httpx.Client, "get", return_value=mock_single):
        contract = client.get_contract("customers", "1.0.0")
        assert contract is not None
        assert contract["dataset"] == "customers"

    # Contract not found (404)
    mock_404 = MagicMock()
    mock_404.status_code = 404

    with patch.object(httpx.Client, "get", return_value=mock_404):
        missing = client.get_contract("nonexistent")
        assert missing is None


# ==============================================================================
# 6. API Client Run History & Filtering Tests
# ==============================================================================

def test_api_client_list_runs_filtering():
    """Test run history retrieval with query parameters."""
    client = SchemaGuardAPIClient()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "items": [{"run_id": "run_001", "dataset_name": "orders", "status": "SUCCESS"}],
        "total": 1,
        "limit": 25,
        "offset": 0,
    }

    with patch.object(httpx.Client, "get", return_value=mock_resp) as mock_get:
        res = client.list_runs(limit=25, offset=0, dataset="orders", status="SUCCESS")
        assert len(res["items"]) == 1
        assert res["total"] == 1

        # Check that query parameters were sent properly
        called_params = mock_get.call_args[1]["params"]
        assert called_params["dataset"] == "orders"
        assert called_params["status"] == "SUCCESS"
        assert called_params["limit"] == 25


# ==============================================================================
# 7. API Client Quarantine & Evolution Filtering Tests
# ==============================================================================

def test_api_client_quarantine_filtering():
    """Test quarantine records retrieval with filters."""
    client = SchemaGuardAPIClient()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "items": [{"quarantine_id": "q1", "violation_field": "email"}],
        "total": 1,
    }

    with patch.object(httpx.Client, "get", return_value=mock_resp) as mock_get:
        res = client.list_quarantine(dataset="customers", violation_rule="pattern")
        assert len(res["items"]) == 1
        called_params = mock_get.call_args[1]["params"]
        assert called_params["dataset"] == "customers"
        assert called_params["violation_rule"] == "pattern"


def test_api_client_evolution_events_filtering():
    """Test schema evolution events list."""
    client = SchemaGuardAPIClient()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "items": [{"event_id": "e1", "is_breaking": True, "impact": "BREAKING"}],
        "total": 1,
    }

    with patch.object(httpx.Client, "get", return_value=mock_resp) as mock_get:
        res = client.list_evolution_events(dataset="customers", is_breaking=True)
        assert len(res["items"]) == 1
        called_params = mock_get.call_args[1]["params"]
        assert called_params["is_breaking"] is True


# ==============================================================================
# 8. Pipeline Trigger Tests
# ==============================================================================

def test_api_client_trigger_pipeline():
    """Test triggering pipeline execution through API client."""
    client = SchemaGuardAPIClient()

    # Success case
    mock_resp_success = MagicMock()
    mock_resp_success.status_code = 201
    mock_resp_success.json.return_value = {
        "run_id": "run_test_123",
        "status": "SUCCESS",
        "published_records": 5,
    }

    with patch.object(httpx.Client, "post", return_value=mock_resp_success):
        res = client.trigger_pipeline_run(
            dataset="customers",
            file_path="data/raw/customers.csv",
        )
        assert res["status"] == "SUCCESS"
        assert res["run_id"] == "run_test_123"

    # Error case
    mock_resp_err = MagicMock()
    mock_resp_err.status_code = 400
    mock_resp_err.json.return_value = {"detail": "Restricted file path"}

    with patch.object(httpx.Client, "post", return_value=mock_resp_err):
        err_res = client.trigger_pipeline_run(
            dataset="customers",
            file_path="/unauthorized/path.csv",
        )
        assert "error" in err_res
        assert err_res["error"] == "Restricted file path"


# ==============================================================================
# 9. Available Data Files Scanner Test
# ==============================================================================

def test_available_data_files_scanner():
    """Verify that get_available_data_files discovers project CSV batches."""
    files = get_available_data_files()
    assert isinstance(files, list)
    assert len(files) >= 2
    # Ensure raw customers and orders CSV files exist in the discovered list
    assert any("customers.csv" in f for f in files)
    assert any("orders.csv" in f for f in files)
