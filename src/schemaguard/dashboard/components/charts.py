"""Interactive Plotly chart visualizations for SchemaGuard Dashboard."""

from typing import Any, Dict, List
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Color Palette
STATUS_COLORS = {
    "SUCCESS": "#22c55e",           # Green
    "PARTIAL_SUCCESS": "#f59e0b",   # Amber / Orange
    "SCHEMA_REJECTED": "#8b5cf6",   # Purple
    "FAILED": "#ef4444",            # Red
}

EVOLUTION_COLORS = {
    "BREAKING": "#ef4444",          # Red
    "NON_BREAKING": "#10b981",      # Emerald Green
}


def render_status_pie_chart(metrics: Dict[str, Any]) -> None:
    """Render a donut chart displaying pipeline run status distribution."""
    labels = ["SUCCESS", "PARTIAL_SUCCESS", "SCHEMA_REJECTED", "FAILED"]
    values = [
        metrics.get("successful_runs", 0),
        metrics.get("partial_success_runs", 0),
        metrics.get("schema_rejected_runs", 0),
        metrics.get("failed_runs", 0),
    ]

    total = sum(values)
    if total == 0:
        st.info("No pipeline execution runs recorded yet.")
        return

    # Filter out 0 count items for clean display
    plot_data = [(l, v) for l, v in zip(labels, values) if v > 0]
    plot_labels = [p[0] for p in plot_data]
    plot_values = [p[1] for p in plot_data]
    colors = [STATUS_COLORS.get(l, "#64748b") for l in plot_labels]

    fig = go.Figure(
        data=[
            go.Pie(
                labels=plot_labels,
                values=plot_values,
                hole=0.55,
                marker=dict(colors=colors, line=dict(color="#ffffff", width=2)),
                textinfo="label+percent",
                hoverinfo="label+value+percent",
            )
        ]
    )
    fig.update_layout(
        title="<b>Pipeline Run Status Distribution</b>",
        margin=dict(t=40, b=20, l=20, r=20),
        height=320,
        legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_records_distribution_chart(metrics: Dict[str, Any]) -> None:
    """Render a donut chart of published clean records vs quarantined invalid records."""
    published = metrics.get("total_published_records", 0)
    quarantined = metrics.get("total_rejected_records", 0)
    total = published + quarantined

    if total == 0:
        st.info("No record counts available.")
        return

    fig = go.Figure(
        data=[
            go.Pie(
                labels=["Published (Clean)", "Quarantined (Violations)"],
                values=[published, quarantined],
                hole=0.55,
                marker=dict(colors=["#3b82f6", "#f43f5e"], line=dict(color="#ffffff", width=2)),
                textinfo="label+percent",
            )
        ]
    )
    fig.update_layout(
        title="<b>Record Quality: Published vs Quarantined</b>",
        margin=dict(t=40, b=20, l=20, r=20),
        height=320,
        legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_dataset_quality_bar_chart(datasets: List[Dict[str, Any]]) -> None:
    """Render a grouped bar chart comparing published and quarantined records per dataset."""
    if not datasets:
        st.info("No dataset metrics recorded yet.")
        return

    df = pd.DataFrame(datasets)
    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            name="Published Records",
            x=df["dataset_name"],
            y=df["total_published_records"],
            marker_color="#3b82f6",
        )
    )
    fig.add_trace(
        go.Bar(
            name="Quarantined Records",
            x=df["dataset_name"],
            y=df["total_quarantined_records"],
            marker_color="#f43f5e",
        )
    )

    fig.update_layout(
        title="<b>Dataset Volume & Health Breakdown</b>",
        barmode="group",
        margin=dict(t=40, b=20, l=20, r=20),
        height=340,
        xaxis_title="Dataset",
        yaxis_title="Record Count",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_execution_history_chart(runs: List[Dict[str, Any]]) -> None:
    """Render an execution timeline chart showing duration and records over time."""
    if not runs:
        st.info("No execution runs to plot.")
        return

    df = pd.DataFrame(runs)
    df["created_at"] = pd.to_datetime(df["created_at"])
    df = df.sort_values("created_at")

    fig = px.scatter(
        df,
        x="created_at",
        y="duration_ms",
        color="status",
        size="total_records",
        hover_data=["run_id", "dataset_name", "published_records", "quarantined_records"],
        color_discrete_map=STATUS_COLORS,
        title="<b>Pipeline Execution History & Performance</b>",
        labels={"created_at": "Timestamp", "duration_ms": "Execution Duration (ms)", "status": "Status"},
    )
    fig.update_traces(marker=dict(opacity=0.85, line=dict(width=1, color="DarkSlateGrey")))
    fig.update_layout(
        margin=dict(t=40, b=20, l=20, r=20),
        height=340,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_schema_evolution_timeline(events: List[Dict[str, Any]]) -> None:
    """Render an interactive chart visualizing schema evolution events by classification."""
    if not events:
        st.info("No schema evolution events detected yet.")
        return

    df = pd.DataFrame(events)
    df["detected_at"] = pd.to_datetime(df["detected_at"])

    # Evolution event count by change type and impact
    fig = px.bar(
        df,
        x="change_type",
        color="impact",
        barmode="group",
        color_discrete_map=EVOLUTION_COLORS,
        hover_data=["dataset_name", "column_name", "contract_version", "detected_at"],
        title="<b>Schema Changes by Classification & Impact</b>",
        labels={"change_type": "Schema Modification Type", "count": "Event Count", "impact": "Compatibility Impact"},
    )
    fig.update_layout(
        margin=dict(t=40, b=20, l=20, r=20),
        height=340,
        xaxis_title="Evolution Change Type",
        yaxis_title="Total Events",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)
