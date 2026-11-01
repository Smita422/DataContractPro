"""Dashboard Overview Page View."""

import streamlit as st

from schemaguard.dashboard.api_client import SchemaGuardAPIClient
from schemaguard.dashboard.components.charts import (
    render_dataset_quality_bar_chart,
    render_execution_history_chart,
    render_records_distribution_chart,
    render_status_pie_chart,
)
from schemaguard.dashboard.components.kpi_cards import render_overview_kpis
from schemaguard.dashboard.components.tables import render_runs_table


def render_overview_view(client: SchemaGuardAPIClient) -> None:
    """Render the main system overview page with KPIs and executive charts."""
    st.markdown("## 📊 System Overview & Operational Health")
    st.markdown(
        "Real-time operational throughput, data contract compliance, and quarantine telemetry across active datasets."
    )

    # 1. Fetch system metrics
    metrics = client.get_metrics_summary()
    if metrics.get("error"):
        st.warning(f"Could not load live metrics from API backend: {metrics.get('error')}")

    # 2. Render KPI Metric Cards
    render_overview_kpis(metrics)

    st.markdown("---")

    # 3. Interactive Visualizations (Row 1)
    col1, col2 = st.columns(2)
    with col1:
        render_status_pie_chart(metrics)
    with col2:
        render_records_distribution_chart(metrics)

    st.markdown("---")

    # 4. Interactive Visualizations (Row 2)
    col3, col4 = st.columns(2)
    with col3:
        datasets_metrics = metrics.get("datasets", [])
        render_dataset_quality_bar_chart(datasets_metrics)

    with col4:
        recent_runs_resp = client.list_runs(limit=25)
        runs_items = recent_runs_resp.get("items", [])
        render_execution_history_chart(runs_items)

    st.markdown("---")

    # 5. Recent Pipeline Runs Table
    st.markdown("### 🕒 Recent Pipeline Executions")
    if runs_items:
        render_runs_table(runs_items[:10])
    else:
        st.info("No pipeline executions recorded yet. Ingest a batch via the CLI or Pipeline Trigger page.")
