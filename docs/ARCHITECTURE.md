# SchemaGuard System Architecture

## 1. System Overview & Engineering Principles

SchemaGuard is an enterprise Data Contract Validation, Schema Evolution, and Observability Platform designed to protect downstream analytical systems from data corruption, contract violations, and unexpected upstream drift.

Built on top of **Python 3.12**, **DuckDB**, **Pandas**, **Pydantic v2**, **FastAPI**, and **Streamlit**, SchemaGuard enforces strict governance between upstream data producers and downstream lakehouse tables.

```
+---------------------------------------------------------------------------------------------------+
|                                          SchemaGuard                                              |
+---------------------------------------------------------------------------------------------------+
|                                                                                                   |
|  [Producer CSV Files]                                                                             |
|          |                                                                                        |
|          v                                                                                        |
|  +---------------------+                                                                          |
|  |   Data Ingestor     | ===> Computes SHA-256 Batch Fingerprint & Ingestion Payload               |
|  +---------------------+                                                                          |
|          |                                                                                        |
|          v                                                                                        |
|  +---------------------+         +-------------------------------------+                          |
|  |  Contract Engine    | <=====> | YAML Contracts (v1.0.0, v1.1.0, ...) |                          |
|  +---------------------+         +-------------------------------------+                          |
|          |                                                                                        |
|          v                                                                                        |
|  +---------------------+                                                                          |
|  | Evolution Analyzer  | ===> Classifies Breaking vs Non-Breaking Schema Drift                     |
|  +---------------------+                                                                          |
|          | (If Breaking: Batch Rejected & Audited)                                                |
|          v (If Non-Breaking / Compatible)                                                         |
|  +---------------------+                                                                          |
|  | Validation Engine   | ===> Vectorized Row & Column Validation, PK Uniqueness, FK Integrity     |
|  +---------------------+                                                                          |
|       /          \                                                                                |
|  [Valid Rows]   [Invalid Rows]                                                                    |
|      |                  |                                                                         |
|      v                  v                                                                         |
|  +-------------+  +-------------------+                                                           |
|  | Transformer |  | Quarantine Engine | ===> Preserves Raw JSON, Lineage & Exact Violation Rules  |
|  +-------------+  +-------------------+                                                           |
|      |                  |                                                                         |
|      +--------+---------+                                                                         |
|               | (Atomic Transaction)                                                              |
|               v                                                                                   |
|  +-----------------------------------------------------------------------------+                  |
|  |                       DuckDB Storage & Publishing Layer                     |                  |
|  |  - Staging Table Insertion & Delta Swap (Zero Unsafe Delete-Before-Insert)  |                  |
|  |  - Upsert into published_customers / published_orders                       |                  |
|  |  - Insertion into quarantined_records & schema_evolution_events             |                  |
|  +-----------------------------------------------------------------------------+                  |
|               |                                                                                   |
|               v                                                                                   |
|  +-----------------------------------------------------------------------------+                  |
|  |                     Source-to-Target Reconciliation Engine                  |                  |
|  |  Formula: Total Received = Valid Published + Quarantined Records            |                  |
|  +-----------------------------------------------------------------------------+                  |
|                                                                                                   |
+---------------------------------------------------------------------------------------------------+
```

---

## 2. Core Architectural Subsystems

### A. Data Ingestion & Batch Fingerprinting
- **Module:** `schemaguard.core.ingestion.DataIngestor`
- **Responsibilities:**
  - Reads source CSV files safely with type preservation.
  - Injects system lineage columns (`_source_filename`, `_source_record_index`).
  - Calculates a deterministic SHA-256 fingerprint from sorted raw contents and structural headers.
  - Distinguishes between `batch_id` (identifies identical input across retries) and `run_id` (identifies an individual execution attempt).
  - Detects duplicate runs and records execution attempts in `pipeline_runs`.

### B. Versioned Data Contract Engine
- **Module:** `schemaguard.core.contract.ContractLoader`
- **Schema Storage:** Version-controlled YAML contracts located at `contracts/<dataset>/v<major>.<minor>.<patch>.yaml`.
- **Validation:** Pydantic v2 data models (`Contract`, `ColumnDefinition`, `ConstraintRules`, `SLADefinition`).
- **Dynamic Resolution:** Resolves explicitly requested semantic versions (e.g., `1.1.0`) or automatically selects the highest semantic version available.

### C. Schema Evolution Analyzer
- **Module:** `schemaguard.core.evolution.SchemaEvolutionAnalyzer`
- **Compatibility Modes:** `BACKWARD` (default), `FORWARD`, `FULL`.
- **Classification Rules:**
  - **Breaking Changes:** Missing required columns, incompatible data type narrowing, nullability constraints tightened (`nullable: true` -> `false`), primary key modifications, restricted enum sets.
  - **Non-Breaking Changes:** Adding optional/nullable columns, adding allowed enum values, safe type widening (e.g., `integer` -> `float`).
- **Batch Enforcement:**
  - `PERMISSIVE` Mode: Warns on non-breaking additions; rejects only breaking changes.
  - `STRICT` Mode: Treats any unexpected column as breaking.
- **Audit Persistence:** Logs all detected changes to `schema_evolution_events`.

### D. High-Performance Vectorized Validation Engine
- **Module:** `schemaguard.core.validator.DataValidator`
- **Execution Throughput:** Up to ~8,688 records/second for customers, and ~2,370 records/second for orders (under full 100k foreign-key relational validation).
- **Optimizations:**
  - Vectorized uniqueness checks for primary keys and unique email fields.
  - Pre-compiled regex patterns and set-based allowed value lookups.
  - Fast ISO-8601 date parsing via native C-level `datetime.fromisoformat`.
  - On-demand row serialization: raw row payloads are converted to JSON dictionaries *only* when quarantine violations are detected.
  - Foreign key validation against DuckDB warehouse via vectorized `isin()` checks.

### E. Quarantine Management
- **Module:** `schemaguard.core.quarantine.QuarantineManager`
- **Lineage Integrity:** Preserves the original file name, source 0-indexed row number, raw unparsed JSON payload, violating column name, violated constraint rule, and human-readable diagnostic message.
- **Zero Loss Guarantee:** Every rejected row is recorded in `quarantined_records` without dropping data.

### F. Idempotent Storage & Staging Upsert
- **Module:** `schemaguard.core.storage.DuckDBStorageManager`
- **Transactional Atomicity:** All writes (published records, quarantine records, audit runs) are wrapped inside DuckDB ACID transactions.
- **Safe Staging Upsert Pattern:**
  1. Valid records are written to a temporary staging table (`staging_<table_name>_<uuid>`).
  2. A targeted `DELETE FROM target WHERE pk IN (SELECT pk FROM staging)` removes conflicting records.
  3. Clean records from staging are inserted into the target table.
  4. Staging table is dropped upon commit.
  5. In case of unexpected disk or execution failure, transaction rolls back cleanly, leaving zero dirty rows.

### G. Source-to-Target Reconciliation Engine
- **Module:** `schemaguard.core.reconciliation.ReconciliationEngine`
- **Balancing Invariant:**
  $$\text{input\_count} = \text{valid\_count} + \text{rejected\_count}$$
- **Warehouse Breakdown:** Distinguishes between new rows inserted (`inserted_count`) and existing primary keys updated (`updated_count`).
- **Audit Logging:** Emits structured Markdown balancing reports and stores `reconciliation_diff` in `pipeline_runs`.

---

## 3. Interfaces & Access Surfaces

1. **CLI (`schemaguard.cli`):** Standalone command-line interface supporting `run`, `status`, `contracts`, `evolution`, and `generate`.
2. **FastAPI REST API (`schemaguard.api`):** Production-ready endpoints with Swagger UI at `/docs`, health monitoring at `/health`, and metrics summaries at `/api/v1/metrics/summary`.
3. **Streamlit Observability Dashboard (`schemaguard.dashboard`):** Real-time monitoring, KPI cards, Plotly charts, interactive contract browser, quarantine inspector, and direct pipeline execution runner.
