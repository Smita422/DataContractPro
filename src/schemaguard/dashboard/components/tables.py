"""Formatted table components for SchemaGuard Dashboard."""

from typing import Any, Dict, List
import pandas as pd
import streamlit as st


def render_runs_table(runs: List[Dict[str, Any]]) -> None:
    """Render a clean interactive table of recent pipeline runs."""
    if not runs:
        st.info("No pipeline runs found matching the selected criteria.")
        return

    table_data = []
    for r in runs:
        table_data.append({
            "Run ID": r.get("run_id"),
            "Dataset": r.get("dataset_name"),
            "Version": r.get("contract_version") or "latest",
            "Status": r.get("status"),
            "Total": r.get("total_records", 0),
            "Valid": r.get("valid_records", 0),
            "Quarantined": r.get("quarantined_records", 0),
            "Published": r.get("published_records", 0),
            "Inserted": r.get("inserted_records", 0),
            "Updated": r.get("updated_records", 0),
            "Reconciled": "BALANCED (0)" if r.get("reconciliation_diff", 0) == 0 else f"DIFF ({r.get('reconciliation_diff')})",
            "Duration (ms)": r.get("duration_ms", 0),
            "Executed At": r.get("created_at"),
        })

    df = pd.DataFrame(table_data)
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_quarantine_table(records: List[Dict[str, Any]]) -> None:
    """Render a clean interactive table of quarantined record violations."""
    if not records:
        st.info("No quarantined records found matching the selected filters.")
        return

    table_data = []
    for q in records:
        table_data.append({
            "Quarantine ID": q.get("quarantine_id"),
            "Record ID": q.get("source_record_id") or f"Row {q.get('row_index')}",
            "Dataset": q.get("dataset_name"),
            "Violating Column": q.get("violation_field"),
            "Rule Violated": q.get("violation_rule"),
            "Error Reason": q.get("error_message"),
            "Run ID": q.get("run_id"),
            "Quarantined At": q.get("quarantined_at"),
        })

    df = pd.DataFrame(table_data)
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_evolution_table(events: List[Dict[str, Any]]) -> None:
    """Render a clean table of schema evolution events."""
    if not events:
        st.info("No schema evolution events detected.")
        return

    table_data = []
    for e in events:
        table_data.append({
            "Dataset": e.get("dataset_name"),
            "Version": e.get("contract_version") or "latest",
            "Column": e.get("column_name") or "-",
            "Change Type": e.get("change_type"),
            "Impact": e.get("impact"),
            "Explanation": e.get("diff_details") or "-",
            "Run ID": e.get("run_id"),
            "Detected At": e.get("detected_at"),
        })

    df = pd.DataFrame(table_data)
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_columns_definition_table(columns: List[Dict[str, Any]]) -> None:
    """Render contract column specifications and constraints."""
    if not columns:
        st.info("No columns defined.")
        return

    rows = []
    for c in columns:
        constraints = c.get("constraints") or {}
        constraint_parts = []
        if constraints.get("min") is not None:
            constraint_parts.append(f"min: {constraints['min']}")
        if constraints.get("max") is not None:
            constraint_parts.append(f"max: {constraints['max']}")
        if constraints.get("min_length") is not None:
            constraint_parts.append(f"min_len: {constraints['min_length']}")
        if constraints.get("max_length") is not None:
            constraint_parts.append(f"max_len: {constraints['max_length']}")
        if constraints.get("pattern"):
            constraint_parts.append(f"regex: {constraints['pattern']}")
        if constraints.get("allowed_values"):
            constraint_parts.append(f"allowed: {constraints['allowed_values']}")

        constraint_str = ", ".join(constraint_parts) if constraint_parts else "-"

        rows.append({
            "Column Name": c.get("name"),
            "Data Type": c.get("type"),
            "Nullable": "Yes" if c.get("nullable") else "No",
            "Primary Key": "PK" if c.get("primary_key") else "-",
            "Unique": "Unique" if c.get("unique") else "-",
            "Rules & Constraints": constraint_str,
            "Description": c.get("description") or "-",
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)
