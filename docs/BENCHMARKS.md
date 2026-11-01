# SchemaGuard Scalability & Performance Benchmarks

This report summarizes the scalability, throughput, latency, and memory consumption characteristics of the SchemaGuard platform, measured across synthetic datasets ranging from **100** to **100,000+** records.

---

## 1. Test Environment

- **Operating System:** Windows 11 (AMD64)
- **Python Runtime:** Python 3.12.4 (64-bit)
- **Core Libraries:** DuckDB 1.x, Pandas 2.x, Pydantic 2.x, Plotly 5.x
- **Test Harness:** `benchmarks/run_benchmarks.py` with `tracemalloc` memory tracing
- **Random Seed:** `42` (deterministic data generation)
- **Execution Date:** November 1, 2026

---

## 2. Benchmark Summary Results

### Customers Dataset
| Record Count | Total Duration (s) | Throughput (Records/Sec) | Peak RAM (MB) | CSV File Size (MB) | Reconciliation Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **100** | 0.0847 | 1,180.3 | 0.28 | 0.009 | **BALANCED (Diff=0)** |
| **1,000** | 0.1151 | 8,688.2 | 0.80 | 0.089 | **BALANCED (Diff=0)** |
| **10,000** | 1.3814 | 7,239.1 | 7.19 | 0.894 | **BALANCED (Diff=0)** |
| **50,000** | 12.4845 | 4,005.0 | 35.53 | 4.511 | **BALANCED (Diff=0)** |
| **100,000** | 22.4509 | 4,454.2 | 70.94 | 9.031 | **BALANCED (Diff=0)** |

### Orders Dataset (with FK lookup against 100,000 customers warehouse)
| Record Count | Total Duration (s) | Throughput (Records/Sec) | Peak RAM (MB) | CSV File Size (MB) | Reconciliation Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **100** | 0.9809 | 101.9 | 71.00 | 0.012 | **BALANCED (Diff=0)** |
| **1,000** | 1.2005 | 833.0 | 71.27 | 0.114 | **BALANCED (Diff=0)** |
| **10,000** | 5.3027 | 1,885.8 | 73.93 | 1.144 | **BALANCED (Diff=0)** |
| **50,000** | 21.4291 | 2,333.3 | 100.58 | 5.718 | **BALANCED (Diff=0)** |
| **100,000** | 42.1810 | 2,370.7 | 141.79 | 11.437 | **BALANCED (Diff=0)** |

---

## 3. Pipeline Phase Latency Breakdown (Orders at Scale)

| Scale | Ingestion (s) | Validation (s) | Transformation (s) | Publishing (s) | Total Time (s) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **10,000** | 0.1560 | 4.3731 | 0.5914 | 0.1822 | **5.3027** |
| **50,000** | 0.6652 | 17.1200 | 2.9791 | 0.6649 | **21.4291** |
| **100,000** | 1.4625 | 34.1034 | 5.1386 | 1.4766 | **42.1810** |

---

## 4. Key Performance Observations & Insights

1. **Near-Linear Scalability ($O(N)$):**
   - Ingestion, validation, transformation, and database publishing scale linearly with record count.
   - 100,000 records ingest, validate, transform, and publish into DuckDB in under **43 seconds** for complex relational orders.
2. **Minimal Memory Footprint & Foreign-Key Preload Overhead:**
   - Peak memory consumption remained under **142 MB** even when processing a 100,000-row batch with live foreign key joins against a pre-loaded 100,000-customer database.
   - **Explanation of 71 MB Baseline Memory for Orders:** To test real-world relational constraints, the orders benchmark pre-loads the full 100,000-record customer warehouse into DuckDB so that `customer_id` foreign keys can be validated live. The ~71 MB initial memory measured by `tracemalloc` represents the storage and index allocation for this 100,000-customer relational warehouse. Incremental order processing scales from this baseline: 100 orders require 71.00 MB total, and 100,000 orders require 141.79 MB (an incremental ~70.8 MB for the 100k orders batch).
3. **Empirical Baseline vs. Optimized Speedup:**
   - **Before Optimization (Iterative Row & Cell Checking):**
     - Customers (1,000 records): Validation took **5.3454 s**; Total Pipeline Duration: **5.4740 s** (182.7 records/sec).
     - Orders (1,000 records): Validation took **12.4254 s**; Total Pipeline Duration: **12.6351 s** (79.1 records/sec).
   - **After Optimization (Vectorized Checks, Pre-compiled Regex, C-level ISO Dates, On-Demand Serialization):**
     - Customers (1,000 records): Validation dropped to **0.0538 s** (**99.3x faster**); Total Pipeline Duration: **0.1151 s** (**8,688.2 records/sec**, a **47.5x overall pipeline speedup**).
     - Orders (1,000 records): Validation dropped to **0.9782 s** (**12.7x faster**); Total Pipeline Duration: **1.2005 s** (**833.0 records/sec**, a **10.5x overall pipeline speedup**).
     - Orders at scale (100,000 records): Reaches **2,370.7 records/sec** end-to-end including database upsert.
4. **Strict Reconciliation Balance Across All Scales:**
   - Across all tests from 100 to 100,000 rows, `reconciliation_diff` was strictly **0**.
   - The invariant $\text{Total Ingested} = \text{Valid Published} + \text{Quarantined}$ held true across 100% of benchmark runs.

---

## 5. Artifacts Generated

The benchmark runner persists structured metrics and interactive visualizations:
- **CSV Data:** `benchmarks/results/benchmark_metrics.csv`
- **JSON Metadata:** `benchmarks/results/benchmark_metrics.json`
- **Interactive Visualization:** `benchmarks/results/benchmark_charts.html` (multi-panel interactive Plotly dashboard featuring duration, throughput, phase breakdown, and memory curves)
