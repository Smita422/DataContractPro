"""Pipeline Runs Execution History View."""

import streamlit as st

from schemaguard.dashboard.api_client import SchemaGuardAPIClient
from schemaguard.dashboard.components.tables import render_evolution_table, render_runs_table


def render_pipeline_runs_view(client: SchemaGuardAPIClient) -> None:
    """Render the pipeline run history exploration page with filtering and drilldown."""
    st.markdown("## 📋 Pipeline Execution History")
    st.markdown(
        "Inspect execution attempts, throughput metrics, source-to-target reconciliation, and schema evolution logs."
    )

    # Filter Controls
    col1, col2, col3, col4 = st.columns([2, 1.5, 1.5, 1.5])
    with col1:
        search_run_id = st.text_input("🔍 Search by Run ID", placeholder="e.g. run_bb8ad6be70e0").strip()
    with col2:
        dataset_filter = st.selectbox("Dataset", ["ALL", "customers", "orders"], index=0)
    with col3:
        status_filter = st.selectbox(
            "Execution Status",
            ["ALL", "SUCCESS", "PARTIAL_SUCCESS", "SCHEMA_REJECTED", "FAILED"],
            index=0,
        )
    with col4:
        limit = st.selectbox("Page Size", [10, 25, 50, 100], index=1)

    # Fetch Run History
    if search_run_id:
        single_run = client.get_run(search_run_id)
        runs_items = [single_run] if single_run else []
        total_runs = len(runs_items)
        if not single_run:
            st.warning(f"No run found with ID: `{search_run_id}`")
    else:
        runs_resp = client.list_runs(
            limit=limit,
            offset=0,
            dataset=dataset_filter,
            status=status_filter,
        )
        runs_items = runs_resp.get("items", [])
        total_runs = runs_resp.get("total", 0)

    st.caption(f"Showing **{len(runs_items)}** of **{total_runs}** matching execution runs")

    # Table of Runs
    render_runs_table(runs_items)

    st.markdown("---")

    # Run Detail Drilldown Section
    st.markdown("### 🔎 Run Execution Detail & Diagnostics")
    run_ids = [r.get("run_id") for r in runs_items if r.get("run_id")]

    if run_ids:
        selected_run_id = st.selectbox("Select Run ID to Inspect:", run_ids, index=0)
        run_detail = client.get_run(selected_run_id)

        if run_detail:
            # Metrics summary for selected run
            m1, m2, m3, m4, m5 = st.columns(5)
            with m1:
                st.metric("Total Records", run_detail.get("total_records", 0))
            with m2:
                st.metric("Published", run_detail.get("published_records", 0))
            with m3:
                st.metric("Quarantined", run_detail.get("quarantined_records", 0))
            with m4:
                st.metric("Inserted / Updated", f"{run_detail.get('inserted_records', 0)} / {run_detail.get('updated_records', 0)}")
            with m5:
                st.metric("Duration", f"{run_detail.get('duration_ms', 0)} ms")

            # Technical details
            st.markdown("#### Technical Metadata")
            st.code(
                f"Batch ID:          {run_detail.get('batch_id')}\n"
                f"Batch Fingerprint: {run_detail.get('batch_fingerprint')}\n"
                f"Dataset:           {run_detail.get('dataset_name')}\n"
                f"Contract Version:  {run_detail.get('contract_version')}\n"
                f"Source File:       {run_detail.get('source_file')}\n"
                f"Reconciliation:    {'BALANCED (diff=0)' if run_detail.get('reconciliation_diff') == 0 else f'UNBALANCED (diff={run_detail.get('reconciliation_diff')})'}\n"
                f"Error Summary:     {run_detail.get('error_summary') or 'None'}",
                language="yaml",
            )

            # Schema evolution changes if any
            schema_events = run_detail.get("schema_evolution_events", [])
            if schema_events:
                st.markdown("#### Detected Schema Evolution Events")
                for evt in schema_events:
                    impact = evt.get("impact")
                    badge = "🔴 BREAKING" if impact == "BREAKING" else "🟢 NON-BREAKING"
                    st.write(
                        f"**{badge}**: Column `{evt.get('column_name')}` | Change: `{evt.get('change_type')}`"
                    )
                    st.caption(f"Reason: {evt.get('explanation')}")
    else:
        st.info("No runs available to inspect.")
