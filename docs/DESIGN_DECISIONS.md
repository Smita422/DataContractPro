# SchemaGuard Architectural & Design Decisions

This document details the architectural rationale, engineering trade-offs, and design decisions adopted in SchemaGuard.

---

## 1. Storage Engine: DuckDB vs Traditional RDBMS / Remote Warehouses

### Decision
DuckDB was selected as the embedded storage, transactional execution, and analytical warehouse engine for SchemaGuard.

### Rationale
1. **In-Process Performance with Zero Daemon Overhead:** DuckDB runs directly inside the Python process space, eliminating network serialization overhead and IPC latency.
2. **Columnar Vectorized Execution:** Analytical queries (aggregations across millions of audit records, lineage joins, window functions) execute in milliseconds using SIMD instructions.
3. **Full ACID Transactional Semantics:** Provides multi-statement transactions (`BEGIN`, `COMMIT`, `ROLLBACK`), which are critical for ensuring atomicity when publishing records and writing audit logs.
4. **Rich Arrow and Pandas Interoperability:** Zero-copy or high-efficiency data exchange between Pandas DataFrames and DuckDB relation pointers.
5. **Portability:** Operates out-of-the-box on Windows, Linux, and macOS without requiring external Docker containers, cloud credentials, or background database servers.

---

## 2. Contract Definition: Versioned Declarative YAML + Pydantic v2

### Decision
Contracts are authored as version-controlled YAML files and validated at runtime into strictly-typed Pydantic v2 domain models.

### Rationale
1. **Producer-Friendly Declarative Syntax:** YAML is the industry-standard human-readable declarative format used across modern data contracts (OpenDataContract, Great Expectations, dbt).
2. **Runtime Type Safety:** Pydantic v2 enforces schema validation, regex syntax correctness, nullability constraints, and type boundaries with sub-millisecond overhead implemented in Rust.
3. **Decoupled Governance:** Contracts live in source control (`contracts/<dataset>/v<version>.yaml`), enabling GitOps workflows, code reviews, and CI/CD validation before contracts are promoted to production.

---

## 3. High-Performance Validation: Vectorized Operations vs Row Iteration

### Decision
Eliminated expensive row-by-row iteration (`iterrows()`, `loc[idx].to_dict()`) in favor of vectorized Pandas operations, cached compiled regexes, and native C-level ISO datetime parsing.

### Rationale & Trade-Offs
- In initial prototypes, calling `.to_dict()` on every cell caused a severe performance bottleneck (~182 records/second for 1,000 records).
- **Optimization Strategy:**
  1. Primary key uniqueness and email uniqueness use vectorized `.duplicated(keep=False)` masks.
  2. Foreign key validation against published customers uses vectorized `.isin()` checks against indexed lookup sets.
  3. Pre-compiled regex patterns outside of row loops.
  4. Native C-level `datetime.fromisoformat` for ISO timestamps with fallback to `pd.to_datetime`.
  5. On-demand row serialization: raw row dictionaries are constructed *only* when a record fails validation and needs to be quarantined.
- **Result:** Validation duration dropped by **99x** for customers and **12x** for orders, lifting total end-to-end pipeline throughput up to **8,688.2 records/sec** for customers and **2,370.7 records/sec** for orders (scaling to 100,000 records).

---

## 4. Idempotency: Staging Upsert vs Delete-Before-Insert

### Decision
SchemaGuard implements safe staging upsert via temporary staging tables rather than destructive `DELETE FROM target WHERE batch_id = ...` or raw overwrites.

### Rationale
- **The Risk of Delete-Before-Insert:** If a pipeline fails midway through execution, a delete-before-insert pattern permanently deletes historical data, leaving the target table empty or corrupt.
- **The SchemaGuard Staging Pattern:**
  1. Clean, transformed records are staged in an ephemeral temporary table (`staging_<dataset>_<uuid>`).
  2. Within an explicit DuckDB transaction:
     - Conflicting records matching primary keys are deleted from the published table (`DELETE FROM target WHERE pk IN (SELECT pk FROM staging)`).
     - New and updated records are copied from staging to target.
     - Quarantine records and audit runs are committed simultaneously.
  3. If an error occurs at any point, DuckDB rolls back the transaction completely. Existing warehouse records remain 100% intact.

---

## 5. Schema Evolution: Compatibility Matrix & Mode Strategy

### Decision
Support `BACKWARD`, `FORWARD`, and `FULL` compatibility modes with runtime `PERMISSIVE` and `STRICT` enforcement.

### Rules Matrix
| Schema Drift Event | Impact Classification | Permissive Behavior | Strict Behavior |
| :--- | :--- | :--- | :--- |
| **Add Optional Column** | Non-Breaking | Allow, warn, and publish | Rejection (if unexpected) |
| **Add Required Column** | Breaking | Reject entire batch, log audit | Reject entire batch |
| **Remove Column** | Breaking | Reject entire batch | Reject entire batch |
| **Narrow Type** (`float` -> `int`) | Breaking | Reject entire batch | Reject entire batch |
| **Widen Type** (`int` -> `float`) | Non-Breaking | Allow and publish | Rejection (if unexpected) |
| **Tighten Nullability** (`true` -> `false`) | Breaking | Reject entire batch | Reject entire batch |
| **Loosen Nullability** (`false` -> `true`) | Non-Breaking | Allow and publish | Allow |
| **Expand Allowed Enums** | Non-Breaking | Allow and publish | Allow |
| **Restrict Allowed Enums** | Breaking | Reject entire batch | Reject entire batch |

---

## 6. Service Decoupling: Core Engine, FastAPI REST, and Streamlit Dashboard

### Decision
Strict three-tier architectural separation:
1. **Core Domain Engine:** Self-contained Python package (`schemaguard.core`) with zero dependency on FastAPI or Streamlit. Can be invoked directly in batch jobs, Airflow operators, or standalone CLI scripts.
2. **FastAPI REST API Layer (`schemaguard.api`):** Exposes HTTP endpoints for triggering runs, retrieving contracts, querying quarantine, and checking system health.
3. **Streamlit Observability Dashboard (`schemaguard.dashboard`):** Communicates with the core engine and backend API via standard HTTP clients (`ApiClient`), maintaining complete separation of concerns and testability.
