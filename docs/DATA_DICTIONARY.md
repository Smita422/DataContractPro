# SchemaGuard Data Dictionary

This document provides complete data dictionary specifications for all internal audit, governance, quarantine, and published domain tables maintained within the SchemaGuard DuckDB analytical database (`data/schemaguard.duckdb`).

---

## 1. Domain Lakehouse Tables (Target Tables)

### `published_customers`
Stores clean, validated, and transformed customer account profiles.

| Column Name | DuckDB Type | Nullable | Primary Key | Constraints / Allowed Values | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `customer_id` | `VARCHAR` | No | **Yes** | Pattern: `^CUST-[0-9]{4,}$` | Unique business identifier for customer |
| `customer_name` | `VARCHAR` | No | No | Length: 2 to 100 characters | Normalized full customer name |
| `email` | `VARCHAR` | No | No | Unique, Valid Email Pattern | Normalized lowercase contact email |
| `city` | `VARCHAR` | Yes | No | String | Residential or billing city |
| `customer_status` | `VARCHAR` | No | No | `active`, `inactive` | Current account lifecycle status |
| `created_at` | `TIMESTAMP` | No | No | ISO-8601 Timestamp | Initial account creation timestamp |
| `_ingested_at` | `TIMESTAMP` | No | No | `CURRENT_TIMESTAMP` | System ingestion timestamp |
| `_batch_id` | `VARCHAR` | No | No | Non-empty string | Source batch identifier |
| `_run_id` | `VARCHAR` | No | No | Non-empty string | Execution attempt identifier |
| `_source_file` | `VARCHAR` | No | No | Non-empty string | Name of raw input file |

---

### `published_orders`
Stores clean, validated, and transformed e-commerce checkout orders.

| Column Name | DuckDB Type | Nullable | Primary Key | Constraints / Allowed Values | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `order_id` | `VARCHAR` | No | **Yes** | Pattern: `^ORD-[0-9]{5,}$` | Unique business identifier for order |
| `customer_id` | `VARCHAR` | No | No | FK -> `published_customers.customer_id` | Referenced customer account |
| `order_date` | `TIMESTAMP` | No | No | Valid Timestamp | Timestamp when order was placed |
| `product_name` | `VARCHAR` | No | No | Length: 1 to 200 characters | Name of purchased product |
| `quantity` | `BIGINT` | No | No | Integer $\ge 1$ | Quantity of units ordered |
| `unit_price` | `DOUBLE` | No | No | Numeric $\ge 0.0$ | Price per single unit in USD |
| `total_amount` | `DOUBLE` | No | No | Derived: `quantity * unit_price` | Computed total order price |
| `order_status` | `VARCHAR` | No | No | `pending`, `shipped`, `delivered`, `cancelled` | Fulfillment lifecycle status |
| `payment_method` | `VARCHAR` | No | No | `card`, `upi`, `cash`, `netbanking` | Payment processing method |
| `delivery_status`| `VARCHAR` | Yes | No | `dispatched`, `in_transit`, `out_for_delivery`, `delivered`, `failed` | Optional shipping status (Contract v1.1.0) |
| `updated_at` | `TIMESTAMP` | No | No | Valid Timestamp | Last update timestamp |
| `_ingested_at` | `TIMESTAMP` | No | No | `CURRENT_TIMESTAMP` | System ingestion timestamp |
| `_batch_id` | `VARCHAR` | No | No | Non-empty string | Source batch identifier |
| `_run_id` | `VARCHAR` | No | No | Non-empty string | Execution attempt identifier |
| `_source_file` | `VARCHAR` | No | No | Non-empty string | Name of raw input file |

---

## 2. Platform Observability & Governance Tables

### `pipeline_runs`
Maintains immutable audit records for every pipeline execution attempt.

| Column Name | DuckDB Type | Nullable | Primary Key | Description |
| :--- | :--- | :--- | :--- | :--- |
| `run_id` | `VARCHAR` | No | **Yes** | Unique identifier for individual execution run |
| `batch_id` | `VARCHAR` | No | No | Identifier for input batch across retries |
| `batch_fingerprint` | `VARCHAR` | Yes | No | Deterministic SHA-256 payload hash |
| `dataset_name` | `VARCHAR` | No | No | Target dataset (`customers`, `orders`) |
| `contract_version` | `VARCHAR` | Yes | No | Semantic version of active contract (e.g. `1.0.0`) |
| `status` | `VARCHAR` | No | No | `SUCCESS`, `PARTIAL_SUCCESS`, `QUARANTINED`, `REJECTED`, `FAILED` |
| `total_records` | `BIGINT` | No | No | Total raw records ingested from source file |
| `valid_records` | `BIGINT` | No | No | Number of records passing contract validation |
| `quarantined_records` | `BIGINT` | No | No | Number of records failing validation |
| `published_records` | `BIGINT` | No | No | Total rows safely published to warehouse |
| `duplicate_records` | `BIGINT` | Yes | No | Existing rows updated via idempotent upsert |
| `updated_records` | `BIGINT` | Yes | No | Rows modified in place |
| `reconciliation_diff` | `BIGINT` | Yes | No | Unbalanced record discrepancy count ($\text{diff} = 0$ is balanced) |
| `start_time` | `TIMESTAMP` | No | No | Run initiation timestamp (UTC) |
| `end_time` | `TIMESTAMP` | Yes | No | Run completion timestamp (UTC) |
| `duration_ms` | `BIGINT` | Yes | No | Total execution wall-clock time in milliseconds |
| `source_file` | `VARCHAR` | No | No | Original source CSV filename |
| `error_summary` | `TEXT` | Yes | No | Diagnostic explanation or rejection message |

---

### `quarantined_records`
Stores rejected raw data records along with complete audit lineage and violation reasons.

| Column Name | DuckDB Type | Nullable | Primary Key | Description |
| :--- | :--- | :--- | :--- | :--- |
| `quarantine_id` | `VARCHAR` | No | **Yes** | Unique UUID identifier for quarantine entry |
| `run_id` | `VARCHAR` | No | No | Foreign reference to `pipeline_runs.run_id` |
| `batch_id` | `VARCHAR` | No | No | Source batch identifier |
| `dataset_name` | `VARCHAR` | No | No | Dataset name (`customers`, `orders`) |
| `row_index` | `BIGINT` | No | No | 0-indexed original line position in source CSV |
| `source_record_id` | `VARCHAR` | Yes | No | Business primary key extracted from raw row |
| `raw_record` | `TEXT` | No | No | Complete original record serialized as JSON |
| `violation_field` | `VARCHAR` | Yes | No | Column name that failed validation |
| `violation_rule` | `VARCHAR` | Yes | No | Contract rule code (e.g., `not_null`, `pattern`, `foreign_key`) |
| `error_message` | `TEXT` | Yes | No | Detailed human-readable failure reason |
| `source_file` | `VARCHAR` | Yes | No | Source CSV file path |
| `quarantined_at` | `TIMESTAMP` | No | No | Timestamp when record was quarantined |

---

### `schema_evolution_events`
Tracks all detected schema drift occurrences and compatibility classifications.

| Column Name | DuckDB Type | Nullable | Primary Key | Description |
| :--- | :--- | :--- | :--- | :--- |
| `event_id` | `VARCHAR` | No | **Yes** | Unique event UUID |
| `run_id` | `VARCHAR` | No | No | Foreign reference to `pipeline_runs.run_id` |
| `batch_id` | `VARCHAR` | No | No | Source batch identifier |
| `dataset_name` | `VARCHAR` | No | No | Target dataset (`customers`, `orders`) |
| `contract_version` | `VARCHAR` | Yes | No | Evaluated contract version |
| `change_type` | `VARCHAR` | No | No | `COLUMN_ADDED`, `COLUMN_REMOVED`, `TYPE_CHANGED`, `NULLABILITY_CHANGED`, `ENUM_EXPANDED`, etc. |
| `is_breaking` | `BOOLEAN` | No | No | Boolean flag indicating whether the evolution is breaking |
| `column_name` | `VARCHAR` | Yes | No | Affected column name |
| `diff_details` | `TEXT` | Yes | No | Detailed explanation of the detected schema modification |
| `detected_at` | `TIMESTAMP` | No | No | Timestamp when evolution event was detected |

---

### `data_contracts`
Internal metadata registry of recognized Data Contracts.

| Column Name | DuckDB Type | Nullable | Primary Key | Description |
| :--- | :--- | :--- | :--- | :--- |
| `dataset_name` | `VARCHAR` | No | **Composite PK** | Dataset identifier |
| `version` | `VARCHAR` | No | **Composite PK** | Semantic version string (`1.0.0`, `1.1.0`) |
| `schema_yaml` | `TEXT` | No | No | Full raw YAML contract specification |
| `registered_at` | `TIMESTAMP` | No | No | Timestamp of registration in metadata store |
| `is_active` | `BOOLEAN` | No | No | Flag indicating if this is the active default contract |
