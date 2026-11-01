"""Schema Evolution Monitoring View."""

import streamlit as st

from schemaguard.dashboard.api_client import SchemaGuardAPIClient
from schemaguard.dashboard.components.charts import render_schema_evolution_timeline
from schemaguard.dashboard.components.tables import render_evolution_table


def render_schema_evolution_view(client: SchemaGuardAPIClient) -> None:
    """Render schema drift, version compatibility, and evolution telemetry view."""
    st.markdown("## 🧬 Schema Evolution & Compatibility Monitoring")
    st.markdown(
        "Monitor schema drift events, structural alterations, and breaking vs non-breaking compatibility classifications."
    )

    # Filters
    col1, col2, col3 = st.columns([2, 2, 2])
    with col1:
        dataset_filter = st.selectbox("Filter Dataset", ["ALL", "customers", "orders"], index=0)
    with col2:
        impact_filter = st.selectbox("Impact Classification", ["ALL", "BREAKING", "NON_BREAKING"], index=0)
    with col3:
        limit = st.selectbox("Limit", [10, 25, 50, 100], index=1)

    is_breaking_param = None
    if impact_filter == "BREAKING":
        is_breaking_param = True
    elif impact_filter == "NON_BREAKING":
        is_breaking_param = False

    # Fetch evolution events
    events_resp = client.list_evolution_events(
        limit=limit,
        offset=0,
        dataset=dataset_filter,
        is_breaking=is_breaking_param,
    )
    events = events_resp.get("items", [])
    total_events = events_resp.get("total", 0)

    # Evolution Metrics summary
    breaking_count = sum(1 for e in events if e.get("is_breaking"))
    non_breaking_count = len(events) - breaking_count

    m1, m2, m3 = st.columns(3)
    with m1:
        st.metric("Total Schema Events", f"{total_events:,}")
    with m2:
        st.metric("Breaking Modifications", f"{breaking_count:,}")
    with m3:
        st.metric("Non-Breaking Evolutions", f"{non_breaking_count:,}")

    st.markdown("---")

    # Interactive Chart
    render_schema_evolution_timeline(events)

    st.markdown("---")

    # Table of Evolution Events
    st.markdown("### 📜 Schema Evolution Event Log")
    render_evolution_table(events)
