"""HTTP Client for SchemaGuard FastAPI Service."""

import os
from typing import Any, Dict, List, Optional
import httpx

DEFAULT_API_URL = "http://127.0.0.1:8000"


class SchemaGuardAPIError(Exception):
    """Raised when an API call fails."""
    pass


class SchemaGuardAPIClient:
    """Client for interacting with the SchemaGuard FastAPI REST backend."""

    def __init__(self, base_url: Optional[str] = None, timeout: float = 10.0):
        raw_url = base_url or os.getenv("SCHEMAGUARD_API_URL", DEFAULT_API_URL)
        self.base_url = raw_url.rstrip("/")
        self.timeout = timeout

    def check_health(self) -> Dict[str, Any]:
        """Check the API service health and database connectivity."""
        url = f"{self.base_url}/api/v1/health"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                res = client.get(url)
                if res.status_code == 200:
                    data = res.json()
                    data["is_available"] = True
                    return data
                return {
                    "is_available": False,
                    "status": "degraded",
                    "database": "disconnected",
                    "detail": f"HTTP {res.status_code}",
                }
        except httpx.RequestError as exc:
            return {
                "is_available": False,
                "status": "unavailable",
                "database": "unreachable",
                "detail": str(exc),
            }

    def get_metrics_summary(self) -> Dict[str, Any]:
        """Fetch system-wide operational and data quality metrics."""
        url = f"{self.base_url}/api/v1/metrics/summary"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                res = client.get(url)
                res.raise_for_status()
                return res.json()
        except Exception as exc:
            return {
                "error": str(exc),
                "total_runs": 0,
                "successful_runs": 0,
                "partial_success_runs": 0,
                "failed_runs": 0,
                "schema_rejected_runs": 0,
                "total_input_records": 0,
                "total_published_records": 0,
                "total_rejected_records": 0,
                "datasets": [],
            }

    def list_contracts(self) -> Dict[str, Any]:
        """List all available datasets and their registered versions."""
        url = f"{self.base_url}/api/v1/contracts"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                res = client.get(url)
                res.raise_for_status()
                return res.json()
        except Exception as exc:
            return {"error": str(exc), "datasets": {}, "total_datasets": 0}

    def get_contract(self, dataset: str, version: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieve full contract details and constraints for a dataset."""
        url = f"{self.base_url}/api/v1/contracts/{dataset}"
        params = {"version": version} if version and version.lower() != "latest" else {}
        try:
            with httpx.Client(timeout=self.timeout) as client:
                res = client.get(url, params=params)
                if res.status_code == 404:
                    return None
                res.raise_for_status()
                return res.json()
        except Exception:
            return None

    def list_runs(
        self,
        limit: int = 50,
        offset: int = 0,
        dataset: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetch paginated pipeline run history."""
        url = f"{self.base_url}/api/v1/runs"
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if dataset and dataset != "ALL":
            params["dataset"] = dataset
        if status and status != "ALL":
            params["status"] = status

        try:
            with httpx.Client(timeout=self.timeout) as client:
                res = client.get(url, params=params)
                res.raise_for_status()
                return res.json()
        except Exception as exc:
            return {"error": str(exc), "items": [], "total": 0, "limit": limit, "offset": offset}

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve complete details for a single pipeline run."""
        url = f"{self.base_url}/api/v1/runs/{run_id}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                res = client.get(url)
                if res.status_code == 404:
                    return None
                res.raise_for_status()
                return res.json()
        except Exception:
            return None

    def list_evolution_events(
        self,
        limit: int = 50,
        offset: int = 0,
        dataset: Optional[str] = None,
        is_breaking: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Fetch paginated schema drift and evolution events."""
        url = f"{self.base_url}/api/v1/evolution/events"
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if dataset and dataset != "ALL":
            params["dataset"] = dataset
        if is_breaking is not None:
            params["is_breaking"] = is_breaking

        try:
            with httpx.Client(timeout=self.timeout) as client:
                res = client.get(url, params=params)
                res.raise_for_status()
                return res.json()
        except Exception as exc:
            return {"error": str(exc), "items": [], "total": 0, "limit": limit, "offset": offset}

    def list_quarantine(
        self,
        limit: int = 50,
        offset: int = 0,
        dataset: Optional[str] = None,
        batch_id: Optional[str] = None,
        run_id: Optional[str] = None,
        violation_rule: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetch paginated quarantined records."""
        url = f"{self.base_url}/api/v1/quarantine"
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if dataset and dataset != "ALL":
            params["dataset"] = dataset
        if batch_id:
            params["batch_id"] = batch_id
        if run_id:
            params["run_id"] = run_id
        if violation_rule:
            params["violation_rule"] = violation_rule

        try:
            with httpx.Client(timeout=self.timeout) as client:
                res = client.get(url, params=params)
                res.raise_for_status()
                return res.json()
        except Exception as exc:
            return {"error": str(exc), "items": [], "total": 0, "limit": limit, "offset": offset}

    def get_quarantine_record(self, record_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve full quarantine details including parsed raw record."""
        url = f"{self.base_url}/api/v1/quarantine/{record_id}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                res = client.get(url)
                if res.status_code == 404:
                    return None
                res.raise_for_status()
                return res.json()
        except Exception:
            return None

    def trigger_pipeline_run(
        self,
        dataset: str,
        file_path: str,
        contract_version: Optional[str] = None,
        schema_mode: str = "PERMISSIVE",
    ) -> Dict[str, Any]:
        """Trigger a validation pipeline execution attempt."""
        url = f"{self.base_url}/api/v1/pipeline/runs"
        payload = {
            "dataset": dataset,
            "file_path": file_path,
            "contract_version": contract_version if contract_version != "latest" else None,
            "schema_mode": schema_mode,
        }
        try:
            with httpx.Client(timeout=self.timeout * 2) as client:
                res = client.post(url, json=payload)
                if res.status_code in (200, 201):
                    return res.json()
                detail = "Execution failed"
                try:
                    err_json = res.json()
                    detail = err_json.get("detail", detail)
                except Exception:
                    detail = res.text or detail
                return {"error": detail, "status_code": res.status_code}
        except Exception as exc:
            return {"error": str(exc), "status_code": 500}
