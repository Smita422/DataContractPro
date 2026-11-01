"""Pipeline Execution Interface View."""

from pathlib import Path
from typing import List
import streamlit as st

from schemaguard.dashboard.api_client import SchemaGuardAPIClient


def get_available_data_files() -> List[str]:
    """Scan approved project data directories for eligible CSV batches.

    Guarantees safety by only offering pre-existing files within the project's data directory.
    """
    data_dir = Path("data")
    if not data_dir.is_dir():
        return []

    csv_files = []
    for f in data_dir.rglob("*.csv"):
        if f.is_file():
            csv_files.append(str(f))
    return sorted(csv_files)


def render_execution_view(client: SchemaGuardAPIClient) -> None:
    """Render interactive pipeline trigger form for ad-hoc ingestion runs."""
    st.markdown("## 🚀 Pipeline Trigger & Ingestion Interface")
    st.markdown(
        "Execute an ad-hoc ingestion batch against the SchemaGuard validation and evolution engine."
    )

    # 1. Fetch registered datasets and versions
    contracts_meta = client.list_contracts()
    datasets_map = contracts_meta.get("datasets", {})
    dataset_names = list(datasets_map.keys()) or ["customers", "orders"]

    # Form parameters
    col1, col2, col3 = st.columns(3)
    with col1:
        dataset = st.selectbox("Target Dataset", dataset_names, index=0)
    with col2:
        versions = ["latest"] + datasets_map.get(dataset, [])
        contract_version = st.selectbox("Contract Version", versions, index=0)
    with col3:
        schema_mode = st.selectbox("Schema Mode", ["PERMISSIVE", "STRICT"], index=0)

    # File Selection from approved project directories
    available_files = get_available_data_files()
    if not available_files:
        st.warning("No CSV files found in the `data/` directory. Please place input CSVs in `data/raw/`.")
        return

    # Pre-select matching file if available
    default_index = 0
    for idx, f in enumerate(available_files):
        if dataset in f.lower():
            default_index = idx
            break

    selected_file = st.selectbox("Approved Input Data Batch", available_files, index=default_index)

    st.caption(f"Selected file path: `{selected_file}`")

    # Run Button
    if st.button("⚡ Trigger Pipeline Execution", type="primary", use_container_width=True):
        with st.spinner(f"Executing SchemaGuard pipeline for {dataset}..."):
            result = client.trigger_pipeline_run(
                dataset=dataset,
                file_path=selected_file,
                contract_version=contract_version,
                schema_mode=schema_mode,
            )

        if result.get("error"):
            st.error(f"Pipeline execution rejected / failed: {result.get('error')}")
        else:
            status = result.get("status")
            if status == "SUCCESS":
                st.success(f"Execution Succeeded! (Status: `{status}`)")
            elif status == "PARTIAL_SUCCESS":
                st.warning(f"Execution Completed with Quarantined Records! (Status: `{status}`)")
            elif status == "SCHEMA_REJECTED":
                st.error(f"Breaking Schema Detected – Publishing Halted! (Status: `{status}`)")
            else:
                st.error(f"Pipeline Failed: `{status}`")

            # Execution metrics
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric("Total Records", result.get("total_records", 0))
            with c2:
                st.metric("Published", result.get("published_records", 0))
            with c3:
                st.metric("Quarantined", result.get("quarantined_records", 0))
            with c4:
                st.metric("Duration", f"{result.get('duration_ms', 0)} ms")

            # Technical details
            st.code(
                f"Run ID:            {result.get('run_id')}\n"
                f"Batch ID:          {result.get('batch_id')}\n"
                f"Batch Fingerprint: {result.get('batch_fingerprint')}\n"
                f"Contract Version:  {result.get('contract_version')}\n"
                f"Reconciliation:    {result.get('reconciliation_status')}\n"
                f"Inserted:          {result.get('inserted_records', 0)}\n"
                f"Updated:           {result.get('updated_records', 0)}\n"
                f"Notice/Errors:     {result.get('error_summary') or 'None'}",
                language="yaml",
            )

            # Schema Changes if detected
            schema_changes = result.get("schema_changes", [])
            if schema_changes:
                st.markdown("#### Schema Evolution Events")
                for ch in schema_changes:
                    impact = ch.get("impact")
                    badge = "🔴 BREAKING" if impact == "BREAKING" else "🟢 NON-BREAKING"
                    st.write(f"**{badge}**: `{ch.get('column_name')}` ({ch.get('change_type')}) - {ch.get('explanation')}")
