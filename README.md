# SchemaGuard: Data Contract Validation & Schema Evolution Platform

**SchemaGuard** is an enterprise data contract validation, schema evolution analysis, and pipeline orchestration platform built with Python, DuckDB, Pandas, YAML, and FastAPI.

It empowers data engineering teams to validate incoming producer batches against version-controlled contracts, detect and classify breaking vs non-breaking schema modifications in real time, quarantine malformed records with granular diagnostic reasons, publish clean records idempotently, and monitor operational health and data quality metrics.

---

## Architecture Overview

```
                      +-----------------------------+
                      |   Producer CSV Data Files   |
                      +--------------+--------------+
                                     |
                                     v
                      +-----------------------------+
                      |        Data Ingestor        |
                      | (SHA-256 Fingerprint,       |
                      |  Batch ID vs Run ID)        |
                      +--------------+--------------+
                                     |
                                     v
                      +-----------------------------+
                      |   Schema Evolution Engine   |
                      | (STRICT / PERMISSIVE Drift, |
                      |  Breaking vs Non-Breaking)  |
                      +--------------+--------------+
                                     |
                                     v
                      +-----------------------------+
                      |     DataValidator Engine    |
                      | (Vectorized Rules, Types,   |
                      |  Bounds, Enums, Regex, FK)  |
                      +-------+-------------+-------+
                              |             |
           Valid Records      |             | Quarantined Records
                              v             v
       +------------------------+         +--------------------------+
       |   Data Transformer     |         |    Quarantine Manager    |
       | (Derived fields, UTC,  |         | (Raw JSON, line index,   |
       |  source audit lineage) |         |  rule, field, error msg) |
       +-----------+------------+         +------------+-------------+
                   |                                   |
                   v                                   v
       +-------------------------------------------------------------+
       |            Transactional DuckDB Storage Engine              |
       |  (Atomic Transactions, Staging Tables, Idempotent Upserts)  |
       +-----------------------------+-------------------------------+
                                     |
                         +-----------+-----------+
                         |           |           |
                         v           v           v
               +-------------------+ +---------+ +---------------------+
               |   CLI Interface   | | FastAPI | | Streamlit Dashboard |
               | (Standalone Tool) | |  REST   | |   (Observability)   |
               +-------------------+ +---------+ +---------------------+
```

---

## Documentation Suite

Comprehensive technical and operational documentation is available in the [`docs/`](docs/) directory:

- [**System Architecture**](docs/ARCHITECTURE.md): Complete subsystem interactions, lifecycle workflows, contract resolution, compatibility matrix, and storage design.
- [**Data Dictionary**](docs/DATA_DICTIONARY.md): Complete schema definitions, column data types, constraints, nullability, and primary/foreign keys for all warehouse and audit tables.
- [**Design Decisions**](docs/DESIGN_DECISIONS.md): Architectural rationale for DuckDB, YAML contracts, vectorized validation optimizations, staging upsert semantics, and service decoupling.
- [**Operations Runbook**](docs/RUNBOOK.md): Step-by-step installation, CLI execution, FastAPI service startup, Streamlit dashboard usage, troubleshooting, and quarantine reprocessing workflows.
- [**Scalability & Benchmarks**](docs/BENCHMARKS.md): Full empirical benchmarks across 100 to 100,000+ records, throughput curves, latency breakdowns, and peak memory analysis.

---

## Key Features

1. **Version-Controlled Data Contracts (YAML):**
   - Declarative contracts specifying column types, nullability, primary keys, uniqueness, allowed enum values, regex patterns, and derived fields.
   - Semantic versioning support (e.g. `1.0.0`, `1.1.0`) with automatic latest-version resolution.
2. **Schema Evolution & Drift Detection:**
   - Detects added columns, removed columns, type modifications, nullability changes, and enum restriction/expansion.
   - Classifies changes as **BREAKING** (halts publishing in strict mode) or **NON-BREAKING** (allows safe evolution with defaults).
3. **Multi-Constraint Row Validation:**
   - Validates regex patterns (e.g. email format), bounds (quantity $\ge 1$, unit_price $\ge 0.0$), domain enum sets, and cross-table foreign key integrity (orders referencing published customers).
   - Records all simultaneous rule violations per rejected row without silent data loss.
4. **Deterministic Idempotency:**
   - Distinct `batch_id` (derived deterministically from file content SHA-256) vs `run_id` (UUID per attempt).
   - Safe staging upsert ensures repeated runs of the same file update records in-place without duplicating data or corrupting state.
5. **Reconciliation & Auditability:**
   - Real-time reconciliation assertion: $\text{input\_records} = \text{valid\_records} + \text{quarantined\_records}$ ($\text{diff} = 0$).
6. **Dual Execution Interfaces:**
   - Standalone CLI for batch scheduling and shell automation.
   - High-performance FastAPI REST API with Swagger documentation at `/docs` and `/redoc`.

---

## Installation & Setup

### Requirements
- Python 3.11+ (Tested on Python 3.12.4 on Windows)
- DuckDB $\ge 1.0.0$

### Setup
Clone the repository and install dependencies in editable mode:

```bash
git clone https://github.com/your-org/SchemaGuard.git
cd SchemaGuard

# Install in editable mode
pip install -e . --no-build-isolation --no-deps
```

---

## Running the CLI

SchemaGuard includes a standalone command-line interface that operates independently of the web service:

```bash
# 1. Inspect registered data contracts
python -m schemaguard contracts

# 2. Ingest customer batch
python -m schemaguard run --dataset customers --file data/raw/customers.csv

# 3. Ingest orders batch (validates FKs against published customers)
python -m schemaguard run --dataset orders --file data/raw/orders.csv

# 4. View recent execution history
python -m schemaguard status
```

---

## Starting the FastAPI REST Service

Start the production FastAPI server using Uvicorn from the project root:

```bash
uvicorn schemaguard.api.main:app --reload --host 127.0.0.1 --port 8000
```

### Interactive Documentation
- **Swagger UI:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc:** [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

---

## Starting the Streamlit Observability Dashboard

SchemaGuard includes an interactive Streamlit + Plotly observability dashboard for real-time data engineering telemetry:

```bash
streamlit run src/schemaguard/dashboard/app.py
```

By default, the dashboard connects to the local FastAPI backend at `http://127.0.0.1:8000`. You can configure a custom API endpoint via the `SCHEMAGUARD_API_URL` environment variable:

```bash
# Windows PowerShell
$env:SCHEMAGUARD_API_URL = "http://localhost:8000"
streamlit run src/schemaguard/dashboard/app.py

# Linux / macOS
export SCHEMAGUARD_API_URL="http://localhost:8000"
streamlit run src/schemaguard/dashboard/app.py
```

### Dashboard Pages
1. **Overview:**
   - Real-time KPI cards: Total Runs, Successful Runs, Partial Successes, Schema Rejections, Failures, Total Ingested, Published Clean, Quarantined Records, and Data Quality SLA Score.
   - Interactive Plotly visualizations: Run Status Distribution Donut, Published vs Quarantined Records Donut, Dataset Health Breakdown, and Performance History Timeline.
   - Recent execution runs log table.
2. **Pipeline Runs:**
   - Paginated historical runs with search by Run ID, dataset filter, and execution status filter.
   - Deep-dive run inspector showing technical metadata, fingerprint, duration, and associated schema evolution changes.
3. **Schema Evolution:**
   - Real-time schema drift event log showing detected modifications, classified as `BREAKING` (red) or `NON_BREAKING` (green).
   - Interactive timeline charting schema changes by type and compatibility impact over time.
4. **Quarantine Management:**
   - Detailed violation browser filterable by dataset, rule keyword, and run ID.
   - Inspect individual rejected records with formatted raw JSON payloads and exact rejection diagnostics.
5. **Contract Explorer:**
   - Interactive YAML contract explorer displaying column data types, nullability, primary keys, uniqueness, allowed enums, bounds, regex rules, and derived expressions.
   - Contract version comparison view (e.g. `orders` `v1.0.0` vs `v1.1.0`).
6. **Pipeline Trigger:**
   - Web interface allowing authorized operators to select an approved CSV data batch from `data/raw/`, configure dataset, contract version, and schema mode, and trigger an ad-hoc pipeline execution with live results.

---

## API Endpoints Reference

### 1. Health & Readiness
`GET /api/v1/health`
- **Response (200 OK):**
```json
{
  "status": "healthy",
  "database": "connected",
  "version": "0.1.0",
  "timestamp": "2026-11-01T15:35:34.177270Z"
}
```

### 2. Contracts Discovery
`GET /api/v1/contracts`
- **Response (200 OK):**
```json
{
  "datasets": {
    "customers": ["1.0.0"],
    "orders": ["1.0.0", "1.1.0"]
  },
  "total_datasets": 2
}
```

`GET /api/v1/contracts/{dataset}?version=1.0.0`
- **Response (200 OK):**
```json
{
  "dataset": "customers",
  "version": "1.0.0",
  "owner": "ecommerce-data-team",
  "domain": "customer-master",
  "compatibility_mode": "BACKWARD",
  "columns": [
    {
      "name": "customer_id",
      "type": "string",
      "nullable": false,
      "primary_key": true,
      "unique": true,
      "constraints": { "min_length": 3, "max_length": 50 }
    },
    {
      "name": "email",
      "type": "string",
      "nullable": false,
      "primary_key": false,
      "unique": true,
      "constraints": {
        "pattern": "^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\\.[a-zA-Z0-9-.]+$"
      }
    },
    {
      "name": "customer_status",
      "type": "string",
      "nullable": false,
      "constraints": {
        "allowed_values": ["active", "inactive"]
      }
    }
  ],
  "derived_fields": []
}
```

### 3. Trigger Pipeline Execution
`POST /api/v1/pipeline/runs`
- **Request Body:**
```json
{
  "dataset": "customers",
  "file_path": "data/raw/customers.csv",
  "contract_version": "1.0.0",
  "schema_mode": "PERMISSIVE"
}
```
- **Response (201 Created):**
```json
{
  "run_id": "run_adec21d5f7b3",
  "batch_id": "batch_customers_edf4280407c3",
  "batch_fingerprint": "edf4280407c36654597fea6eee897d6c13015899fa9023146eaf68641f7c9106",
  "dataset": "customers",
  "contract_version": "1.0.0",
  "status": "PARTIAL_SUCCESS",
  "total_records": 6,
  "valid_records": 5,
  "quarantined_records": 1,
  "published_records": 5,
  "inserted_records": 0,
  "updated_records": 5,
  "reconciliation_diff": 0,
  "reconciliation_status": "BALANCED (diff=0)",
  "duration_ms": 53,
  "source_file": "customers.csv",
  "error_summary": "1 records quarantined",
  "schema_changes": []
}
```

### 4. Run Execution History
`GET /api/v1/runs?limit=10&offset=0&dataset=customers`
- **Response (200 OK):**
```json
{
  "items": [
    {
      "run_id": "run_adec21d5f7b3",
      "batch_id": "batch_customers_edf4280407c3",
      "batch_fingerprint": "edf4280407c36654...",
      "dataset_name": "customers",
      "contract_version": "1.0.0",
      "status": "PARTIAL_SUCCESS",
      "total_records": 6,
      "valid_records": 5,
      "quarantined_records": 1,
      "published_records": 5,
      "inserted_records": 0,
      "updated_records": 5,
      "reconciliation_diff": 0,
      "duration_ms": 53,
      "source_file": "customers.csv",
      "created_at": "2026-11-01T15:35:34.400Z"
    }
  ],
  "total": 6,
  "limit": 10,
  "offset": 0
}
```

### 5. Quarantine Inspection & Diagnostics
`GET /api/v1/quarantine?limit=10&dataset=orders`
- **Response (200 OK):**
```json
{
  "items": [
    {
      "quarantine_id": "e531353a-5d67-477a-84af-82978c6ce860",
      "run_id": "run_504582c7bc90",
      "batch_id": "batch_orders_9886a21a8c51",
      "dataset_name": "orders",
      "row_index": 5,
      "source_record_id": "ORD-99999",
      "violation_field": "customer_id",
      "violation_rule": "foreign_key: published_customers",
      "error_message": "Referenced customer_id 'CUST-8888' does not exist in published_customers.",
      "source_file": "orders.csv",
      "quarantined_at": "2026-11-01T15:35:34.500Z"
    }
  ],
  "total": 18,
  "limit": 10,
  "offset": 0
}
```

`GET /api/v1/quarantine/{record_id}`
- **Response (200 OK):**
```json
{
  "quarantine_id": "e531353a-5d67-477a-84af-82978c6ce860",
  "run_id": "run_504582c7bc90",
  "batch_id": "batch_orders_9886a21a8c51",
  "dataset_name": "orders",
  "row_index": 5,
  "source_record_id": "ORD-99999",
  "violation_field": "customer_id",
  "violation_rule": "foreign_key: published_customers",
  "error_message": "Referenced customer_id 'CUST-8888' does not exist in published_customers.",
  "source_file": "orders.csv",
  "quarantined_at": "2026-11-01T15:35:34.500Z",
  "raw_record": {
    "order_id": "ORD-99999",
    "customer_id": "CUST-8888",
    "order_date": "2026-11-01 12:15:00",
    "product_name": "Phantom Item",
    "quantity": "-2",
    "unit_price": "50.00",
    "order_status": "invalid_status",
    "payment_method": "bitcoin",
    "updated_at": "2026-11-01 12:20:00"
  }
}
```

### 6. Live Metrics Summary
`GET /api/v1/metrics/summary`
- **Response (200 OK):**
```json
{
  "total_runs": 6,
  "successful_runs": 0,
  "partial_success_runs": 6,
  "failed_runs": 0,
  "schema_rejected_runs": 0,
  "total_input_records": 36,
  "total_published_records": 30,
  "total_rejected_records": 6,
  "datasets": [
    {
      "dataset_name": "customers",
      "total_runs": 3,
      "successful_runs": 0,
      "partial_success_runs": 3,
      "failed_runs": 0,
      "schema_rejected_runs": 0,
      "total_input_records": 18,
      "total_published_records": 15,
      "total_quarantined_records": 3
    },
    {
      "dataset_name": "orders",
      "total_runs": 3,
      "successful_runs": 0,
      "partial_success_runs": 3,
      "failed_runs": 0,
      "schema_rejected_runs": 0,
      "total_input_records": 18,
      "total_published_records": 15,
      "total_quarantined_records": 3
    }
  ]
}
```

---

## Synthetic Data Generator

SchemaGuard features a high-performance synthetic data generator capable of producing deterministic clean or controlled corrupted datasets:

```bash
# Generate 10,000 valid customer profiles
python -m schemaguard generate --dataset customers --count 10000 --output data/customers_10k.csv --seed 42

# Generate 50,000 orders referencing customers
python -m schemaguard generate --dataset orders --count 50000 --customers-file data/customers_10k.csv --output data/orders_50k.csv --seed 42

# Controlled negative corruption (10% corruption with null fields, bad enums, and duplicate keys)
python -m schemaguard generate --dataset customers --count 1000 --corruption-rate 0.10 --output data/corrupted_customers.csv
```

---

## Scalability & Performance Benchmarks

SchemaGuard includes an automated benchmarking suite (`benchmarks/run_benchmarks.py`) with memory tracing (`tracemalloc`) and interactive Plotly visualization generation:

```bash
python benchmarks/run_benchmarks.py --sizes 100,1000,10000,50000,100000 --seed 42
```

### Empirical Benchmark Summary (Python 3.12.4 on Windows AMD64)

| Dataset | Record Count | Total Duration (s) | Throughput (Records/Sec) | Peak RAM (MB) | File Size (MB) | Reconciliation |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Customers** | 100 | 0.0847 | 1,180.3 | 0.28 | 0.009 | Balanced (Diff=0) |
| **Customers** | 1,000 | 0.1151 | 8,688.2 | 0.80 | 0.089 | Balanced (Diff=0) |
| **Customers** | 10,000 | 1.3814 | 7,239.1 | 7.19 | 0.894 | Balanced (Diff=0) |
| **Customers** | 50,000 | 12.4845 | 4,005.0 | 35.53 | 4.511 | Balanced (Diff=0) |
| **Customers** | 100,000 | 22.4509 | 4,454.2 | 70.94 | 9.031 | Balanced (Diff=0) |
| **Orders** | 100 | 0.9809 | 101.9 | 71.00 | 0.012 | Balanced (Diff=0) |
| **Orders** | 1,000 | 1.2005 | 833.0 | 71.27 | 0.114 | Balanced (Diff=0) |
| **Orders** | 10,000 | 5.3027 | 1,885.8 | 73.93 | 1.144 | Balanced (Diff=0) |
| **Orders** | 50,000 | 21.4291 | 2,333.3 | 100.58 | 5.718 | Balanced (Diff=0) |
| **Orders** | 100,000 | 42.1810 | 2,370.7 | 141.79 | 11.437 | Balanced (Diff=0) |

*Full analysis available in [docs/BENCHMARKS.md](docs/BENCHMARKS.md) and interactive charts in `benchmarks/results/benchmark_charts.html`.*

---

## Test Suite Execution

SchemaGuard includes 105 comprehensive integration, unit, API, and edge-case tests covering storage, data contracts, evolution analysis, pipeline orchestration, REST API services, dashboard components, synthetic generator, and scale edge cases:

```bash
python -m pytest -v
```

Output:
```
====================== 105 passed, 2 warnings in 30.08s =======================
```

---

## Project Structure

```
SchemaGuard/
├── benchmarks/
│   ├── run_benchmarks.py
│   └── results/
│       ├── benchmark_charts.html
│       ├── benchmark_metrics.csv
│       └── benchmark_metrics.json
├── contracts/
│   ├── customers/
│   │   └── v1.0.0.yaml
│   └── orders/
│       ├── v1.0.0.yaml
│       └── v1.1.0.yaml
├── data/
│   ├── raw/
│   │   ├── customers.csv
│   │   └── orders.csv
│   └── schemaguard.duckdb
├── docs/
│   ├── ARCHITECTURE.md
│   ├── BENCHMARKS.md
│   ├── DATA_DICTIONARY.md
│   ├── DESIGN_DECISIONS.md
│   └── RUNBOOK.md
├── src/
│   └── schemaguard/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── api/
│       │   ├── __init__.py
│       │   ├── main.py
│       │   ├── dependencies.py
│       │   ├── schemas.py
│       │   └── routes/
│       │       ├── __init__.py
│       │       ├── contracts.py
│       │       ├── evolution.py
│       │       ├── health.py
│       │       ├── metrics.py
│       │       ├── pipeline.py
│       │       ├── quarantine.py
│       │       └── runs.py
│       ├── dashboard/
│       │   ├── __init__.py
│       │   ├── app.py
│       │   ├── api_client.py
│       │   ├── components/
│       │   │   ├── __init__.py
│       │   │   ├── charts.py
│       │   │   ├── kpi_cards.py
│       │   │   ├── sidebar.py
│       │   │   └── tables.py
│       │   └── views/
│       │       ├── __init__.py
│       │       ├── contracts.py
│       │       ├── execution.py
│       │       ├── overview.py
│       │       ├── pipeline_runs.py
│       │       ├── quarantine.py
│       │       └── schema_evolution.py
│       ├── core/
│       │   ├── __init__.py
│       │   ├── contract.py
│       │   ├── evolution.py
│       │   ├── generator.py
│       │   ├── ingestion.py
│       │   ├── pipeline.py
│       │   ├── quarantine.py
│       │   ├── reconciliation.py
│       │   ├── storage.py
│       │   ├── transformation.py
│       │   └── validator.py
│       └── utils/
│           ├── __init__.py
│           └── logger.py
├── tests/
│   ├── conftest.py
│   ├── test_api.py
│   ├── test_contract.py
│   ├── test_dashboard.py
│   ├── test_edge_cases.py
│   ├── test_evolution.py
│   ├── test_generator.py
│   ├── test_pipeline.py
│   └── test_storage.py
├── pyproject.toml
└── README.md
```
