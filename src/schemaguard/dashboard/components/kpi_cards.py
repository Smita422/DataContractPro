"""KPI Metric Cards for SchemaGuard Observability Dashboard."""

from typing import Any, Dict, Optional
import streamlit as st


def calculate_data_quality_pct(published_records: int, input_records: int) -> Optional[float]:
    """Calculate overall data quality percentage.

    Formula:
        Data Quality % = (Total Published Records / Total Input Records) * 100

    Returns:
        None if input_records is 0 or negative (displays 'N/A' rather than misleading 100%),
        otherwise float rounded to 2 decimal places.
    """
    if input_records <= 0:
        return None
    pct = (published_records / input_records) * 100.0
    return round(max(0.0, min(100.0, pct)), 2)


def render_overview_kpis(metrics: Dict[str, Any]) -> None:
    """Render top-level KPI metric cards for system operational health."""
    total_runs = metrics.get("total_runs", 0)
    successful_runs = metrics.get("successful_runs", 0)
    partial_success_runs = metrics.get("partial_success_runs", 0)
    failed_runs = metrics.get("failed_runs", 0)
    schema_rejected_runs = metrics.get("schema_rejected_runs", 0)

    input_records = metrics.get("total_input_records", 0)
    published_records = metrics.get("total_published_records", 0)
    rejected_records = metrics.get("total_rejected_records", 0)

    quality_pct = calculate_data_quality_pct(published_records, input_records)
    quality_display = f"{quality_pct:.1f}%" if quality_pct is not None else "N/A"
    quality_delta = f"{quality_pct - 95.0:.1f}% vs 95% SLA" if (quality_pct is not None and total_runs > 0) else None

    # Row 1: Pipeline Execution KPIs
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric(label="Total Pipeline Runs", value=f"{total_runs:,}")
    with col2:
        st.metric(label="Successful Runs", value=f"{successful_runs:,}")
    with col3:
        st.metric(label="Partial Success Runs", value=f"{partial_success_runs:,}")
    with col4:
        st.metric(label="Schema Rejections", value=f"{schema_rejected_runs:,}")
    with col5:
        st.metric(label="Failed Runs", value=f"{failed_runs:,}")

    st.markdown("<div style='margin-bottom: 12px;'></div>", unsafe_allow_html=True)

    # Row 2: Data Volume & Quality KPIs
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric(label="Total Ingested Records", value=f"{input_records:,}")
    with c2:
        st.metric(label="Published Clean Records", value=f"{published_records:,}")
    with c3:
        st.metric(label="Quarantined Records", value=f"{rejected_records:,}")
    with c4:
        help_text = (
            "Formula: (Total Published Records / Total Ingested Records) * 100. "
            "Displays N/A when no input records exist."
        )
        st.metric(
            label="Data Quality SLA Score",
            value=quality_display,
            delta=quality_delta,
            help=help_text,
        )

    st.caption("ℹ️ *Metrics represent cumulative historical execution totals across all active pipeline runs in DuckDB.*")
