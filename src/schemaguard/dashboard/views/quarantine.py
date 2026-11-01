"""Quarantine Management & Record Inspection View."""

import streamlit as st

from schemaguard.dashboard.api_client import SchemaGuardAPIClient
from schemaguard.dashboard.components.tables import render_quarantine_table


def render_quarantine_view(client: SchemaGuardAPIClient) -> None:
    """Render quarantine investigation view with filtering and raw JSON payload diagnostics."""
    st.markdown("## ☣️ Quarantine Management & Diagnostics")
    st.markdown(
        "Inspect quarantined records rejected during data quality validation, identify violating rules, and review original raw payloads."
    )

    # Filter Controls
    col1, col2, col3, col4 = st.columns([1.5, 2, 2, 1.5])
    with col1:
        dataset_filter = st.selectbox("Dataset", ["ALL", "customers", "orders"], index=0)
    with col2:
        rule_filter = st.text_input("Filter Violation Rule", placeholder="e.g. pattern, foreign_key, min").strip()
    with col3:
        run_id_filter = st.text_input("Filter by Run ID", placeholder="e.g. run_bb8ad6be70e0").strip()
    with col4:
        limit = st.selectbox("Page Size", [15, 30, 50, 100], index=0)

    # Fetch quarantined records
    quarantine_resp = client.list_quarantine(
        limit=limit,
        offset=0,
        dataset=dataset_filter,
        run_id=run_id_filter if run_id_filter else None,
        violation_rule=rule_filter if rule_filter else None,
    )
    records = quarantine_resp.get("items", [])
    total_quarantined = quarantine_resp.get("total", 0)

    st.metric("Total Quarantined Entries", f"{total_quarantined:,}")
    st.caption(f"Showing **{len(records)}** of **{total_quarantined}** records matching active criteria")

    # Table of quarantined items
    render_quarantine_table(records)

    st.markdown("---")

    # Detailed Record Inspection Section
    st.markdown("### 🔍 Raw Record Payload & Failure Investigation")
    if records:
        options = [
            f"{q.get('quarantine_id')} | {q.get('source_record_id') or 'Row ' + str(q.get('row_index'))} ({q.get('violation_field')})"
            for q in records
        ]
        selected_option = st.selectbox("Select Quarantined Item to Inspect:", options, index=0)
        selected_qid = selected_option.split(" | ")[0]

        record_detail = client.get_quarantine_record(selected_qid)
        if record_detail:
            c1, c2, c3 = st.columns(3)
            with c1:
                st.write(f"**Source Record ID:** `{record_detail.get('source_record_id') or 'None'}`")
                st.write(f"**Dataset:** `{record_detail.get('dataset_name')}`")
                st.write(f"**Row Index:** `{record_detail.get('row_index')}`")
            with c2:
                st.write(f"**Violating Field:** `{record_detail.get('violation_field')}`")
                st.write(f"**Violation Rule:** `{record_detail.get('violation_rule')}`")
                st.write(f"**Source File:** `{record_detail.get('source_file')}`")
            with c3:
                st.write(f"**Run ID:** `{record_detail.get('run_id')}`")
                st.write(f"**Batch ID:** `{record_detail.get('batch_id')}`")
                st.write(f"**Timestamp:** `{record_detail.get('quarantined_at')}`")

            st.error(f"**Validation Rejection Reason:** {record_detail.get('error_message')}")

            st.markdown("#### Original Raw Record JSON Payload")
            raw_payload = record_detail.get("raw_record", {})
            st.json(raw_payload)
    else:
        st.info("No quarantined records match the current filter selection.")
