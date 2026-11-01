"""SchemaGuard Scalability and Performance Benchmark Suite.

Benchmarks synthetic data generation, CSV ingestion, data validation,
deterministic transformation, DuckDB transactional publishing, and memory
consumption across scales from 100 to 100,000+ records.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import time
import tracemalloc
from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from schemaguard.core.contract import load_contract
from schemaguard.core.generator import SyntheticDataGenerator
from schemaguard.core.ingestion import DataIngestor
from schemaguard.core.reconciliation import ReconciliationEngine
from schemaguard.core.storage import DuckDBStorageManager
from schemaguard.core.transformation import DataTransformer
from schemaguard.core.validator import DataValidator
from schemaguard.utils.logger import logger


def run_single_benchmark(
    dataset_name: str,
    record_count: int,
    seed: int,
    temp_dir: Path,
    customers_file: Optional[Path] = None,
) -> Dict[str, Any]:
    """Execute timed benchmark for a single dataset and record count."""
    print(f"\n--- Benchmarking {dataset_name.upper()} ({record_count:,} records) ---")

    # 1. Generation Phase
    gen_file = temp_dir / f"{dataset_name}_{record_count}.csv"
    generator = SyntheticDataGenerator(seed=seed)

    t_gen_start = time.perf_counter()
    if dataset_name == "customers":
        df_gen = generator.generate_customers(count=record_count, output_file=gen_file)
    else:
        df_gen = generator.generate_orders(
            count=record_count,
            customers_file=customers_file,
            output_file=gen_file,
            include_delivery_status=True,
        )
    gen_duration = time.perf_counter() - t_gen_start
    file_size_bytes = gen_file.stat().st_size
    file_size_mb = round(file_size_bytes / (1024 * 1024), 3)

    print(f"  [Generation]     {gen_duration:.4f} s | File Size: {file_size_mb} MB ({len(df_gen):,} rows)")

    # 2. Pipeline Execution Phase with Memory Tracing
    test_db = temp_dir / f"bench_{dataset_name}_{record_count}.duckdb"
    storage = DuckDBStorageManager(db_path=test_db)
    contract = load_contract(dataset_name)

    # Ingestion
    tracemalloc.start()
    t_ingest_start = time.perf_counter()
    raw_df, payload = DataIngestor.read_csv(gen_file, dataset_name=dataset_name)
    ingest_duration = time.perf_counter() - t_ingest_start

    # If orders, ensure customers are in storage for FK validation
    if dataset_name == "orders" and customers_file and customers_file.exists():
        cust_raw, cust_payload = DataIngestor.read_csv(customers_file, dataset_name="customers")
        cust_contract = load_contract("customers")
        c_valid, _ = DataValidator.validate(
            raw_df=cust_raw,
            contract=cust_contract,
            batch_id=cust_payload.batch_id,
            run_id=cust_payload.run_id,
            source_file=cust_payload.source_filename,
            storage=storage,
        )
        c_clean = DataTransformer.transform(
            dataset_name="customers",
            valid_df=c_valid,
            batch_id=cust_payload.batch_id,
            run_id=cust_payload.run_id,
            source_file=cust_payload.source_filename,
        )
        with storage.transaction() as tx_cust:
            storage.upsert_published_records("customers", c_clean, "customer_id", con=tx_cust)

    # Validation
    t_val_start = time.perf_counter()
    valid_df, val_result = DataValidator.validate(
        raw_df=raw_df,
        contract=contract,
        batch_id=payload.batch_id,
        run_id=payload.run_id,
        source_file=payload.source_filename,
        storage=storage,
    )
    val_duration = time.perf_counter() - t_val_start

    # Transformation
    t_trans_start = time.perf_counter()
    clean_df = DataTransformer.transform(
        dataset_name=dataset_name,
        valid_df=valid_df,
        batch_id=payload.batch_id,
        run_id=payload.run_id,
        source_file=payload.source_filename,
    )
    trans_duration = time.perf_counter() - t_trans_start

    # Publishing
    t_pub_start = time.perf_counter()
    pk_col = contract.get_primary_key() or f"{dataset_name[:-1]}_id"
    with storage.transaction() as tx_con:
        upsert_res = storage.upsert_published_records(
            table_name=dataset_name,
            df=clean_df,
            primary_key=pk_col,
            con=tx_con,
            return_details=True,
        )
        if val_result.quarantine_records:
            q_dicts = [r.to_dict() for r in val_result.quarantine_records]
            storage.insert_quarantine_records(q_dicts, con=tx_con)
    pub_duration = time.perf_counter() - t_pub_start

    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak_mem_mb = round(peak_mem / (1024 * 1024), 2)

    total_pipeline_duration = ingest_duration + val_duration + trans_duration + pub_duration
    throughput_rps = round(record_count / total_pipeline_duration, 1) if total_pipeline_duration > 0 else 0.0

    # Reconciliation
    reconciliation = ReconciliationEngine.reconcile(
        batch_id=payload.batch_id,
        run_id=payload.run_id,
        dataset_name=dataset_name,
        input_count=val_result.input_count,
        valid_count=val_result.valid_count,
        rejected_count=val_result.rejected_count,
        inserted_count=upsert_res["inserted_count"],
        updated_count=upsert_res["updated_count"],
    )

    print(f"  [Ingestion]      {ingest_duration:.4f} s")
    print(f"  [Validation]     {val_duration:.4f} s")
    print(f"  [Transformation] {trans_duration:.4f} s")
    print(f"  [Publishing]     {pub_duration:.4f} s")
    print(f"  [Total Duration] {total_pipeline_duration:.4f} s ({throughput_rps:,.1f} records/sec)")
    print(f"  [Peak Memory]    {peak_mem_mb} MB")
    print(f"  [Reconciliation] Input={record_count:,} | Published={len(clean_df):,} | Rejected={val_result.rejected_count} (Diff={reconciliation.reconciliation_diff})")

    return {
        "dataset": dataset_name,
        "record_count": record_count,
        "gen_duration_sec": round(gen_duration, 4),
        "file_size_mb": file_size_mb,
        "ingest_duration_sec": round(ingest_duration, 4),
        "val_duration_sec": round(val_duration, 4),
        "trans_duration_sec": round(trans_duration, 4),
        "pub_duration_sec": round(pub_duration, 4),
        "total_duration_sec": round(total_pipeline_duration, 4),
        "throughput_rps": throughput_rps,
        "valid_records": val_result.valid_count,
        "rejected_records": val_result.rejected_count,
        "published_records": upsert_res["published_count"],
        "inserted_records": upsert_res["inserted_count"],
        "updated_records": upsert_res["updated_count"],
        "reconciliation_diff": reconciliation.reconciliation_diff,
        "reconciliation_status": "BALANCED" if reconciliation.is_balanced else "UNBALANCED",
        "peak_mem_mb": peak_mem_mb,
    }


def generate_benchmark_plots(df: pd.DataFrame, output_html: Path) -> None:
    """Generate high-resolution interactive Plotly charts of benchmark results."""
    fig = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=(
            "Total Pipeline Duration vs Dataset Size",
            "Processing Throughput (Records / Sec) vs Scale",
            "Pipeline Phase Duration Breakdown (Orders)",
            "Peak Memory Consumption vs Dataset Size",
        ),
        vertical_spacing=0.15,
        horizontal_spacing=0.12,
    )

    customers_df = df[df["dataset"] == "customers"]
    orders_df = df[df["dataset"] == "orders"]

    # 1. Total Duration vs Size
    fig.add_trace(
        go.Scatter(
            x=customers_df["record_count"],
            y=customers_df["total_duration_sec"],
            mode="lines+markers",
            name="Customers Duration (s)",
            line=dict(color="#3b82f6", width=2.5),
            marker=dict(size=8),
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=orders_df["record_count"],
            y=orders_df["total_duration_sec"],
            mode="lines+markers",
            name="Orders Duration (s)",
            line=dict(color="#10b981", width=2.5),
            marker=dict(size=8),
        ),
        row=1, col=1,
    )

    # 2. Throughput vs Scale
    fig.add_trace(
        go.Scatter(
            x=customers_df["record_count"],
            y=customers_df["throughput_rps"],
            mode="lines+markers",
            name="Customers Throughput",
            line=dict(color="#3b82f6", dash="dot"),
            marker=dict(size=8),
        ),
        row=1, col=2,
    )
    fig.add_trace(
        go.Scatter(
            x=orders_df["record_count"],
            y=orders_df["throughput_rps"],
            mode="lines+markers",
            name="Orders Throughput",
            line=dict(color="#10b981", dash="dot"),
            marker=dict(size=8),
        ),
        row=1, col=2,
    )

    # 3. Phase Duration Breakdown for Orders
    if not orders_df.empty:
        fig.add_trace(
            go.Bar(name="Ingestion", x=orders_df["record_count"].astype(str), y=orders_df["ingest_duration_sec"], marker_color="#6366f1"),
            row=2, col=1,
        )
        fig.add_trace(
            go.Bar(name="Validation", x=orders_df["record_count"].astype(str), y=orders_df["val_duration_sec"], marker_color="#ec4899"),
            row=2, col=1,
        )
        fig.add_trace(
            go.Bar(name="Transform", x=orders_df["record_count"].astype(str), y=orders_df["trans_duration_sec"], marker_color="#f59e0b"),
            row=2, col=1,
        )
        fig.add_trace(
            go.Bar(name="Publish", x=orders_df["record_count"].astype(str), y=orders_df["pub_duration_sec"], marker_color="#10b981"),
            row=2, col=1,
        )

    # 4. Memory vs Size
    fig.add_trace(
        go.Scatter(
            x=orders_df["record_count"],
            y=orders_df["peak_mem_mb"],
            mode="lines+markers",
            name="Peak RAM (MB)",
            line=dict(color="#f43f5e", width=2.5),
            marker=dict(size=8),
        ),
        row=2, col=2,
    )

    fig.update_layout(
        title="<b>SchemaGuard Scalability and Performance Benchmark Suite</b>",
        height=800,
        barmode="stack",
        margin=dict(t=60, b=40, l=40, r=40),
        legend=dict(orientation="h", yanchor="bottom", y=-0.12, xanchor="center", x=0.5),
    )
    fig.write_html(str(output_html))
    print(f"\n[OK] Interactive benchmark plots saved to: {output_html}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SchemaGuard Scalability Benchmarks")
    parser.add_argument(
        "--sizes",
        default="100,1000,10000,50000,100000",
        help="Comma-separated record counts (default: 100,1000,10000,50000,100000)",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    parser.add_argument("--output-dir", default="benchmarks/results", help="Directory for output files")
    args = parser.parse_args()

    record_sizes = [int(s.strip()) for s in args.sizes.split(",") if s.strip()]
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 75)
    print(" SchemaGuard Scalability & Performance Benchmark Suite")
    print(f" Environment: Python {platform.python_version()} on {platform.system()} ({platform.machine()})")
    print(f" Test Scales: {record_sizes}")
    print(f" Random Seed: {args.seed}")
    print("=" * 75)

    benchmark_records: List[Dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="sg_bench_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)

        # 1. Benchmark Customers across all sizes
        last_cust_file = None
        for count in record_sizes:
            res_cust = run_single_benchmark("customers", count, args.seed, tmp_dir)
            benchmark_records.append(res_cust)
            last_cust_file = tmp_dir / f"customers_{count}.csv"

        # 2. Benchmark Orders across all sizes (referencing generated customers)
        for count in record_sizes:
            res_order = run_single_benchmark("orders", count, args.seed, tmp_dir, customers_file=last_cust_file)
            benchmark_records.append(res_order)

    # Save results to CSV and JSON
    bench_df = pd.DataFrame(benchmark_records)
    csv_out = out_dir / "benchmark_metrics.csv"
    json_out = out_dir / "benchmark_metrics.json"
    html_out = out_dir / "benchmark_charts.html"

    bench_df.to_csv(csv_out, index=False)
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "environment": {
                    "python_version": platform.python_version(),
                    "os": platform.system(),
                    "arch": platform.machine(),
                },
                "results": benchmark_records,
            },
            f,
            indent=2,
        )

    print(f"\n[OK] Benchmark metrics saved to:")
    print(f"  - CSV:  {csv_out}")
    print(f"  - JSON: {json_out}")

    # Generate charts
    generate_benchmark_plots(bench_df, html_out)

    print("\n" + "=" * 75)
    print(" Summary Table:")
    print("=" * 75)
    summary_cols = ["dataset", "record_count", "total_duration_sec", "throughput_rps", "peak_mem_mb", "file_size_mb"]
    print(bench_df[summary_cols].to_string(index=False))
    print("=" * 75)


if __name__ == "__main__":
    main()
