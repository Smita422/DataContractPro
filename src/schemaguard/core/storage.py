"""DuckDB storage and metadata manager for SchemaGuard."""

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional
import duckdb
import pandas as pd

from schemaguard.utils.logger import logger

DEFAULT_DB_PATH = Path("data") / "schemaguard.duckdb"

SCHEMA_INIT_DDL = """
-- 1. Data Contracts Registry Table
CREATE TABLE IF NOT EXISTS data_contracts (
    contract_id VARCHAR PRIMARY KEY,
    dataset_name VARCHAR NOT NULL,
    version VARCHAR NOT NULL,
    schema_yaml TEXT NOT NULL,
    compatibility_mode VARCHAR NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Pipeline Execution Runs Table
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id VARCHAR PRIMARY KEY,
    batch_id VARCHAR NOT NULL,
    batch_fingerprint VARCHAR NOT NULL,
    dataset_name VARCHAR NOT NULL,
    contract_version VARCHAR,
    status VARCHAR NOT NULL,
    total_records BIGINT NOT NULL DEFAULT 0,
    valid_records BIGINT NOT NULL DEFAULT 0,
    quarantined_records BIGINT NOT NULL DEFAULT 0,
    reconciliation_diff BIGINT NOT NULL DEFAULT 0,
    published_records BIGINT DEFAULT 0,
    duplicate_records BIGINT DEFAULT 0,
    updated_records BIGINT DEFAULT 0,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    duration_ms BIGINT DEFAULT 0,
    source_file VARCHAR,
    error_summary TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Schema Evolution Audit Table
CREATE TABLE IF NOT EXISTS schema_evolution_events (
    event_id VARCHAR PRIMARY KEY,
    run_id VARCHAR NOT NULL,
    batch_id VARCHAR NOT NULL,
    dataset_name VARCHAR NOT NULL,
    contract_version VARCHAR,
    change_type VARCHAR NOT NULL,
    is_breaking BOOLEAN NOT NULL,
    column_name VARCHAR,
    diff_details TEXT,
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. Quarantined Records Table
CREATE TABLE IF NOT EXISTS quarantined_records (
    quarantine_id VARCHAR PRIMARY KEY,
    run_id VARCHAR NOT NULL,
    batch_id VARCHAR NOT NULL,
    dataset_name VARCHAR NOT NULL,
    row_index BIGINT NOT NULL,
    source_record_id VARCHAR,
    raw_record TEXT NOT NULL,
    violation_field VARCHAR,
    violation_rule VARCHAR,
    error_message TEXT,
    source_file VARCHAR,
    quarantined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5. Published E-Commerce Domain Tables
CREATE TABLE IF NOT EXISTS published_customers (
    customer_id VARCHAR PRIMARY KEY,
    customer_name VARCHAR NOT NULL,
    email VARCHAR NOT NULL,
    city VARCHAR,
    customer_status VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL,
    _sg_batch_id VARCHAR NOT NULL,
    _sg_run_id VARCHAR NOT NULL,
    _sg_source_file VARCHAR,
    _sg_loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS published_orders (
    order_id VARCHAR PRIMARY KEY,
    customer_id VARCHAR NOT NULL,
    order_date TIMESTAMP NOT NULL,
    product_name VARCHAR NOT NULL,
    quantity BIGINT NOT NULL,
    unit_price DOUBLE NOT NULL,
    total_amount DOUBLE NOT NULL,
    order_status VARCHAR NOT NULL,
    payment_method VARCHAR NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    delivery_status VARCHAR,
    _sg_batch_id VARCHAR NOT NULL,
    _sg_run_id VARCHAR NOT NULL,
    _sg_source_file VARCHAR,
    _sg_loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class DuckDBStorageManager:
    """Manages DuckDB connections, schema migrations, and transactional writes."""

    def __init__(self, db_path: Optional[str | Path] = None, read_only: bool = False):
        if db_path is None:
            self.db_path = str(DEFAULT_DB_PATH)
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        else:
            self.db_path = str(db_path)
            if self.db_path != ":memory:":
                Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self.read_only = read_only
        self._con = duckdb.connect(database=self.db_path, read_only=self.read_only)
        self._init_database()

    def get_connection(self) -> duckdb.DuckDBPyConnection:
        """Return the active DuckDB connection."""
        return self._con

    def _init_database(self) -> None:
        """Initialize metadata and domain tables."""
        if self.read_only:
            return

        self._con.execute(SCHEMA_INIT_DDL)
        logger.debug(f"DuckDB schema initialized at {self.db_path}")

    @contextmanager
    def transaction(self) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        """Context manager providing atomic transactional execution.

        Automatically issues BEGIN TRANSACTION, commits on clean exit,
        and executes ROLLBACK on any unhandled exception.
        """
        self._con.execute("BEGIN TRANSACTION")
        try:
            yield self._con
            self._con.execute("COMMIT")
        except Exception as exc:
            self._con.execute("ROLLBACK")
            logger.error(f"Transaction failed and was rolled back: {exc}")
            raise

    def execute(self, query: str, params: Optional[List[Any]] = None) -> None:
        """Execute a DDL/DML statement against the database."""
        if params:
            self._con.execute(query, params)
        else:
            self._con.execute(query)

    def fetch_all(self, query: str, params: Optional[List[Any]] = None) -> List[Any]:
        """Execute a query and fetch all rows."""
        if params:
            return self._con.execute(query, params).fetchall()
        return self._con.execute(query).fetchall()

    def fetch_one(self, query: str, params: Optional[List[Any]] = None) -> Optional[Any]:
        """Execute a query and fetch a single row."""
        if params:
            return self._con.execute(query, params).fetchone()
        return self._con.execute(query).fetchone()

    def fetch_df(self, query: str, params: Optional[List[Any]] = None) -> pd.DataFrame:
        """Execute a query and return results as a Pandas DataFrame."""
        if params:
            return self._con.execute(query, params).df()
        return self._con.execute(query).df()

    def record_pipeline_run(self, run_data: Dict[str, Any]) -> None:
        """Insert or update a pipeline run record."""
        query = """
        INSERT INTO pipeline_runs (
            run_id, batch_id, batch_fingerprint, dataset_name, contract_version,
            status, total_records, valid_records, quarantined_records,
            reconciliation_diff, published_records, duplicate_records, updated_records,
            start_time, end_time, duration_ms, source_file, error_summary, created_at
        ) VALUES (
            $run_id, $batch_id, $batch_fingerprint, $dataset_name, $contract_version,
            $status, $total_records, $valid_records, $quarantined_records,
            $reconciliation_diff, $published_records, $duplicate_records, $updated_records,
            $start_time, $end_time, $duration_ms, $source_file, $error_summary, CURRENT_TIMESTAMP
        )
        ON CONFLICT (run_id) DO UPDATE SET
            status = EXCLUDED.status,
            valid_records = EXCLUDED.valid_records,
            quarantined_records = EXCLUDED.quarantined_records,
            reconciliation_diff = EXCLUDED.reconciliation_diff,
            published_records = EXCLUDED.published_records,
            duplicate_records = EXCLUDED.duplicate_records,
            updated_records = EXCLUDED.updated_records,
            end_time = EXCLUDED.end_time,
            duration_ms = EXCLUDED.duration_ms,
            error_summary = EXCLUDED.error_summary;
        """
        self._con.execute(
            query,
            {
                "run_id": run_data["run_id"],
                "batch_id": run_data["batch_id"],
                "batch_fingerprint": run_data.get("batch_fingerprint", ""),
                "dataset_name": run_data["dataset_name"],
                "contract_version": run_data.get("contract_version"),
                "status": run_data["status"],
                "total_records": run_data.get("total_records", 0),
                "valid_records": run_data.get("valid_records", 0),
                "quarantined_records": run_data.get("quarantined_records", 0),
                "reconciliation_diff": run_data.get("reconciliation_diff", 0),
                "published_records": run_data.get("published_records", 0),
                "duplicate_records": run_data.get("duplicate_records", 0),
                "updated_records": run_data.get("updated_records", 0),
                "start_time": run_data["start_time"],
                "end_time": run_data.get("end_time"),
                "duration_ms": run_data.get("duration_ms", 0),
                "source_file": run_data.get("source_file"),
                "error_summary": run_data.get("error_summary"),
            },
        )

    def log_schema_evolution(self, event_data: Dict[str, Any]) -> None:
        """Record a schema evolution event."""
        query = """
        INSERT INTO schema_evolution_events (
            event_id, run_id, batch_id, dataset_name, contract_version,
            change_type, is_breaking, column_name, diff_details, detected_at
        ) VALUES (
            $event_id, $run_id, $batch_id, $dataset_name, $contract_version,
            $change_type, $is_breaking, $column_name, $diff_details, CURRENT_TIMESTAMP
        );
        """
        self._con.execute(query, event_data)

    def insert_quarantine_records(
        self, records: List[Dict[str, Any]], con: Optional[duckdb.DuckDBPyConnection] = None
    ) -> None:
        """Batch insert quarantined records into the database."""
        if not records:
            return

        df = pd.DataFrame(records)
        cols = [
            "quarantine_id",
            "run_id",
            "batch_id",
            "dataset_name",
            "row_index",
            "source_record_id",
            "raw_record",
            "violation_field",
            "violation_rule",
            "error_message",
            "source_file",
        ]
        # Ensure all columns exist
        for c in cols:
            if c not in df.columns:
                df[c] = None

        df_to_insert = df[cols]

        target_con = con if con is not None else self._con
        run_ids = list({r["run_id"] for r in records if "run_id" in r and r["run_id"]})
        for r_id in run_ids:
            target_con.execute("DELETE FROM quarantined_records WHERE run_id = $1", [r_id])

        target_con.execute(
            """
            INSERT INTO quarantined_records (
                quarantine_id, run_id, batch_id, dataset_name, row_index,
                source_record_id, raw_record, violation_field, violation_rule,
                error_message, source_file
            ) SELECT * FROM df_to_insert;
            """
        )

    def upsert_published_records(
        self,
        table_name: str,
        df: pd.DataFrame,
        primary_key: str,
        con: Optional[duckdb.DuckDBPyConnection] = None,
        return_details: bool = False,
    ) -> Any:
        """Safe and idempotent upsert into published domain table using staging swap.

        Avoids unsafe delete-before-insert by staging records, deleting only
        matching incoming primary keys within the same transaction, and inserting
        the new records.
        """
        if df.empty:
            return {"published_count": 0, "inserted_count": 0, "updated_count": 0} if return_details else 0

        target_table = f"published_{table_name}"
        staging_table = f"stg_{table_name}_{pd.Timestamp.now().strftime('%Y%m%d%H%M%S%f')}"

        def _do_upsert(active_con: duckdb.DuckDBPyConnection) -> Any:
            active_con.execute(
                f"CREATE TEMPORARY TABLE {staging_table} AS SELECT * FROM df"
            )

            # Count rows that already exist in target to distinguish updates from inserts
            updated_count = active_con.execute(
                f"SELECT COUNT(*) FROM {target_table} WHERE {primary_key} IN (SELECT {primary_key} FROM {staging_table})"
            ).fetchone()[0]
            inserted_count = len(df) - updated_count

            # Remove rows in target that exist in staging (safe atomic upsert)
            active_con.execute(
                f"""
                DELETE FROM {target_table}
                WHERE {primary_key} IN (SELECT {primary_key} FROM {staging_table})
                """
            )

            # Insert staged rows into target by name (handles schema variations gracefully)
            active_con.execute(
                f"""
                INSERT INTO {target_table} BY NAME
                SELECT * FROM {staging_table}
                """
            )
            active_con.execute(f"DROP TABLE IF EXISTS {staging_table}")

            if return_details:
                return {
                    "published_count": len(df),
                    "inserted_count": inserted_count,
                    "updated_count": updated_count,
                }
            return len(df)

        if con is not None:
            return _do_upsert(con)
        else:
            with self.transaction() as tx_con:
                return _do_upsert(tx_con)

    def close(self) -> None:
        """Close database connection."""
        if self._con:
            self._con.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
