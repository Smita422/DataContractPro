"""Command-line interface (CLI) for SchemaGuard pipeline execution and inspection."""

import argparse
from pathlib import Path
import sys
from typing import Optional

from schemaguard.core.contract import list_all_contracts
from schemaguard.core.generator import SyntheticDataGenerator
from schemaguard.core.pipeline import PipelineOrchestrator
from schemaguard.core.storage import DuckDBStorageManager


def format_table(headers: list[str], rows: list[list[str]]) -> str:
    """Format tabular data into a neat ASCII table."""
    if not rows:
        return "No records found."
    widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(str(val)))

    sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"
    head_str = "| " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers)) + " |"

    data_lines = []
    for row in rows:
        line = "| " + " | ".join(str(val).ljust(widths[i]) for i, val in enumerate(row)) + " |"
        data_lines.append(line)

    return "\n".join([sep, head_str, sep] + data_lines + [sep])


def handle_run(args: argparse.Namespace) -> int:
    """Execute data pipeline run for a dataset file."""
    file_path = Path(args.file)
    if not file_path.exists():
        print(f"[ERROR] Specified file does not exist: {file_path}", file=sys.stderr)
        return 1

    storage = DuckDBStorageManager(db_path=args.db) if args.db else DuckDBStorageManager()
    orchestrator = PipelineOrchestrator(storage=storage)

    print(f"\n{'='*70}")
    print(f" SchemaGuard Pipeline Execution: {args.dataset.upper()}")
    print(f"{'='*70}")
    print(f"Input File:     {file_path}")
    print(f"Dataset:        {args.dataset}")
    print(f"Contract Ver:   {args.version or 'latest'}")
    print(f"Schema Mode:    {args.mode.upper()}")
    print(f"{'='*70}\n")

    result = orchestrator.run(
        file_path=file_path,
        dataset_name=args.dataset,
        version=args.version,
        mode=args.mode,
    )

    status_icon = "[OK]" if result.status in ("SUCCESS", "PARTIAL_SUCCESS") else "[FAILED]"
    print(f"\n{status_icon} Execution Status: {result.status}\n")

    metrics_headers = ["Metric", "Value"]
    metrics_rows = [
        ["Run ID", result.run_id],
        ["Batch ID", result.batch_id],
        ["Batch Fingerprint", f"{result.batch_fingerprint[:16]}..."],
        ["Contract Version", result.contract_version or "N/A"],
        ["Execution Duration", f"{result.duration_ms} ms"],
        ["Total Input Records", str(result.total_records)],
        ["Valid Records", str(result.valid_records)],
        ["Quarantined Records", str(result.quarantined_records)],
        ["Published Records", str(result.published_records)],
        ["Inserted Records", str(result.inserted_records)],
        ["Updated (Duplicates)", str(result.updated_records)],
        ["Reconciliation Diff", str(result.reconciliation_diff)],
        ["Reconciliation Status", "BALANCED (diff=0)" if result.reconciliation_diff == 0 else "UNBALANCED"],
    ]
    print(format_table(metrics_headers, metrics_rows))

    if result.error_summary:
        print(f"\n[!] Notice / Errors: {result.error_summary}")

    if result.schema_changes:
        print("\n--- Schema Evolution Events Detected ---")
        ev_headers = ["Column", "Change Type", "Impact", "Explanation"]
        ev_rows = [
            [c.column_name, c.change_type.value, c.classification.value, c.explanation]
            for c in result.schema_changes
        ]
        print(format_table(ev_headers, ev_rows))

    return 0 if result.status in ("SUCCESS", "PARTIAL_SUCCESS") else 1


def handle_status(args: argparse.Namespace) -> int:
    """Display recent pipeline runs."""
    storage = DuckDBStorageManager(db_path=args.db) if args.db else DuckDBStorageManager()
    query = """
    SELECT run_id, dataset_name, contract_version, status, total_records,
           valid_records, quarantined_records, duration_ms, created_at
    FROM pipeline_runs
    ORDER BY created_at DESC
    LIMIT ?
    """
    rows = storage.fetch_all(query, [args.limit])
    headers = [
        "Run ID",
        "Dataset",
        "Version",
        "Status",
        "Total",
        "Valid",
        "Quarantined",
        "Duration (ms)",
        "Executed At",
    ]
    str_rows = [[str(col) for col in row] for row in rows]
    print("\nRecent SchemaGuard Pipeline Runs:")
    print(format_table(headers, str_rows))
    return 0


def handle_contracts(args: argparse.Namespace) -> int:
    """List registered contracts."""
    contracts = list_all_contracts()
    print("\nRegistered Data Contracts:")
    headers = ["Dataset", "Available Versions"]
    rows = [[ds, ", ".join(vers)] for ds, vers in sorted(contracts.items())]
    print(format_table(headers, rows))
    return 0


def handle_evolution(args: argparse.Namespace) -> int:
    """Handle querying and displaying recent schema evolution events."""
    storage = DuckDBStorageManager(db_path=args.db) if args.db else DuckDBStorageManager()
    query = "SELECT event_id, dataset_name, change_type, column_name, is_breaking, diff_details, detected_at FROM schema_evolution_events ORDER BY detected_at DESC LIMIT ?"
    events = storage.fetch_all(query, [args.limit])
    if not events:
        print("\nNo schema evolution events recorded.")
        return 0

    print(f"\nRecent Schema Evolution Events (Last {len(events)}):")
    headers = ["Dataset", "Change Type", "Column", "Impact", "Explanation", "Detected At"]
    rows = [
        [
            str(e[1]),
            str(e[2]),
            str(e[3] or "-"),
            "BREAKING" if e[4] else "NON_BREAKING",
            (str(e[5])[:55] + "..." if len(str(e[5])) > 55 else str(e[5])),
            str(e[6]),
        ]
        for e in events
    ]
    print(format_table(headers, rows))
    return 0


def handle_generate(args: argparse.Namespace) -> int:
    """Generate synthetic contract-compliant or negative test data."""
    generator = SyntheticDataGenerator(seed=args.seed)
    output_path = args.output or f"data/raw/{args.dataset}.csv"

    print(f"\n{'='*70}")
    print(f" SchemaGuard Synthetic Data Generator")
    print(f"{'='*70}")
    print(f"Dataset:         {args.dataset}")
    print(f"Count:           {args.count:,} records")
    print(f"Seed:            {args.seed}")
    print(f"Output File:     {output_path}")
    print(f"Corruption Rate: {args.corruption_rate * 100:.1f}%")
    print(f"{'='*70}\n")

    if args.dataset == "customers":
        df = generator.generate_customers(
            count=args.count,
            output_file=output_path,
            corruption_rate=args.corruption_rate,
        )
    else:  # orders
        df = generator.generate_orders(
            count=args.count,
            customers_file=args.customers_file or "data/raw/customers.csv",
            output_file=output_path,
            include_delivery_status=args.delivery_status,
            corruption_rate=args.corruption_rate,
        )

    file_size_kb = Path(output_path).stat().st_size / 1024
    print(f"[OK] Generated {len(df):,} records into '{output_path}' ({file_size_kb:.1f} KB)")
    return 0


def main(args: Optional[list[str]] = None) -> int:
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        prog="schemaguard",
        description="SchemaGuard: Data Contract Validation & Schema Evolution Engine",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: run
    run_parser = subparsers.add_parser("run", help="Run ingestion and validation on a dataset file")
    run_parser.add_argument("--dataset", required=True, choices=["customers", "orders"], help="Dataset name")
    run_parser.add_argument("--file", required=True, help="Path to input CSV file")
    run_parser.add_argument("--version", help="Data contract version (e.g. 1.0.0 or 1.1.0)")
    run_parser.add_argument(
        "--mode",
        choices=["PERMISSIVE", "STRICT"],
        default="PERMISSIVE",
        help="Schema validation mode (default: PERMISSIVE)",
    )
    run_parser.add_argument("--db", help="Path to DuckDB database file")

    # Command: status
    status_parser = subparsers.add_parser("status", help="Display recent execution history")
    status_parser.add_argument("--limit", type=int, default=10, help="Number of runs to show (default: 10)")
    status_parser.add_argument("--db", help="Path to DuckDB database file")

    # Command: contracts
    contracts_parser = subparsers.add_parser("contracts", help="List registered contracts")

    # Command: evolution
    evolution_parser = subparsers.add_parser("evolution", help="Display recorded schema evolution events")
    evolution_parser.add_argument("--limit", type=int, default=10, help="Number of events to show (default: 10)")
    evolution_parser.add_argument("--db", help="Path to DuckDB database file")

    # Command: generate
    gen_parser = subparsers.add_parser("generate", help="Generate synthetic test datasets")
    gen_parser.add_argument("--dataset", required=True, choices=["customers", "orders"], help="Dataset name")
    gen_parser.add_argument("--count", type=int, default=1000, help="Number of records (default: 1000)")
    gen_parser.add_argument("--output", help="Output file path (default: data/raw/<dataset>.csv)")
    gen_parser.add_argument("--seed", type=int, default=42, help="Deterministic random seed (default: 42)")
    gen_parser.add_argument("--customers-file", help="Path to customers CSV for order foreign keys")
    gen_parser.add_argument("--corruption-rate", type=float, default=0.0, help="Controlled corruption rate 0.0-1.0 (default: 0.0)")
    gen_parser.add_argument("--delivery-status", action="store_true", help="Include optional delivery_status (orders v1.1.0)")

    parsed = parser.parse_args(args)
    if not parsed.command:
        parser.print_help()
        return 0

    if parsed.command == "run":
        return handle_run(parsed)
    elif parsed.command == "status":
        return handle_status(parsed)
    elif parsed.command == "contracts":
        return handle_contracts(parsed)
    elif parsed.command == "evolution":
        return handle_evolution(parsed)
    elif parsed.command == "generate":
        return handle_generate(parsed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
