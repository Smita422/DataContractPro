# SchemaGuard Operations Runbook

A guide for deploying, running, operating, and troubleshooting the SchemaGuard Data Contract Platform.

---

## 1. Prerequisites & Environment Setup

- **Operating System:** Windows 10/11, Linux (Ubuntu 20.04+), or macOS
- **Python Version:** Python 3.11 or Python 3.12 (Tested on Python 3.12.4)
- **Dependencies:** Pandas, DuckDB, FastAPI, Uvicorn, Streamlit, Plotly, PyYAML, Pydantic v2, Pytest

### Installation
Clone or navigate to the project directory and install in editable mode:
```bash
cd e:\Projects\SchemaGuard
pip install -e . --no-build-isolation --no-deps
```

Verify installation:
```bash
python -m schemaguard --help
```

---

## 2. CLI Usage Guide

The SchemaGuard CLI is accessible via `python -m schemaguard` or `schemaguard`.

### A. Execute Pipeline Run
Ingest, validate, and publish a CSV batch against a versioned contract:
```bash
# Ingest customers with default active contract
python -m schemaguard run data/customers.csv --dataset customers

# Ingest orders against explicit contract version in strict mode
python -m schemaguard run data/orders.csv --dataset orders --version 1.0.0 --mode STRICT
```

### B. Generate Synthetic Data
Generate realistic, contract-compliant test data:
```bash
# Generate 1,000 clean customers
python -m schemaguard generate --dataset customers --count 1000 --output data/customers_1k.csv --seed 42

# Generate 5,000 orders referencing customers file
python -m schemaguard generate --dataset orders --count 5000 --customers-file data/customers_1k.csv --output data/orders_5k.csv --seed 42

# Generate negative corrupted customers (15% corruption rate)
python -m schemaguard generate --dataset customers --count 500 --corruption-rate 0.15 --output data/corrupted_customers.csv
```

### C. Check Pipeline Status & Recent Runs
```bash
# List last 10 runs
python -m schemaguard status --limit 10

# Inspect specific run details
python -m schemaguard status --run-id run_abc123
```

### D. List Registered Contracts
```bash
python -m schemaguard contracts
```

---

## 3. Running Services

### A. Start FastAPI REST Service
Start the API service with Uvicorn:
```bash
python -m uvicorn schemaguard.api.main:app --host 0.0.0.0 --port 8000 --reload
```
- Interactive Swagger UI: `http://localhost:8000/docs`
- ReDoc Documentation: `http://localhost:8000/redoc`
- Health Check: `http://localhost:8000/health`
- Metrics Summary: `http://localhost:8000/api/v1/metrics/summary`

### B. Start Streamlit Observability Dashboard
Start the real-time observability dashboard:
```bash
python -m streamlit run src/schemaguard/dashboard/app.py --server.port 8501
```
- Open browser to `http://localhost:8501`
- Set `SCHEMAGUARD_API_URL` environment variable if the API runs on a custom port/host.

---

## 4. Running Benchmarks & Verifications

### Run Scalability Benchmarks
Execute the automated performance benchmark suite:
```bash
python benchmarks/run_benchmarks.py --sizes 100,1000,10000,50000,100000 --seed 42
```
Outputs generated:
- `benchmarks/results/benchmark_metrics.csv`
- `benchmarks/results/benchmark_metrics.json`
- `benchmarks/results/benchmark_charts.html` (Interactive Plotly visualizations)

### Run Test Suite
Execute the full 105 automated unit, integration, API, and edge-case tests:
```bash
python -m pytest -v
```

---

## 5. Troubleshooting & Operational Scenarios

### Scenario 1: Orders Quarantined Due to Foreign Key Violation
- **Symptom:** Ingested orders show `PARTIAL_SUCCESS` or `QUARANTINED` with error `foreign_key: published_customers`.
- **Root Cause:** The referenced `customer_id` has not yet been ingested and published to `published_customers`.
- **Resolution:**
  1. Ingest the upstream customer batch first:
     ```bash
     python -m schemaguard run data/customers.csv --dataset customers
     ```
  2. Reprocess the original orders file:
     ```bash
     python -m schemaguard run data/orders.csv --dataset orders
     ```
  3. The orders will now validate and publish cleanly to `published_orders`.

### Scenario 2: Batch Rejection Due to Breaking Schema Change
- **Symptom:** Pipeline run returns `REJECTED` with error details explaining schema differences.
- **Root Cause:** A required column is missing, a column was deleted, or a column data type was modified incompatibly.
- **Resolution:**
  1. Inspect the recorded evolution event:
     ```bash
     python -m schemaguard evolution
     ```
  2. Check `schema_evolution_events` table for exact column names and difference reasons.
  3. Work with data producer to update the data file or issue a new major contract version (e.g. `v2.0.0.yaml`).

### Scenario 3: Database Reset & Recovery
If testing in a fresh sandbox and you wish to clear or reset the database:
```bash
# Safely remove the DuckDB file
rm data/schemaguard.duckdb
# DuckDBStorageManager will automatically re-initialize all DDL schemas on next run.
```
