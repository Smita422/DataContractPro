"""Main entry point for SchemaGuard Streamlit Observability Dashboard."""

import streamlit as st

from schemaguard.dashboard.api_client import SchemaGuardAPIClient
from schemaguard.dashboard.components.sidebar import render_sidebar
from schemaguard.dashboard.views.contracts import render_contracts_view
from schemaguard.dashboard.views.execution import render_execution_view
from schemaguard.dashboard.views.overview import render_overview_view
from schemaguard.dashboard.views.pipeline_runs import render_pipeline_runs_view
from schemaguard.dashboard.views.quarantine import render_quarantine_view
from schemaguard.dashboard.views.schema_evolution import render_schema_evolution_view

# Configure Streamlit page
st.set_page_config(
    page_title="SchemaGuard – Data Contract Observability Platform",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Apply sleek styling
st.markdown(
    """
    <style>
    /* Professional Typography & Spacing */
    .block-container {
        padding-top: 1.8rem;
        padding-bottom: 2.5rem;
    }
    div[data-testid="stMetric"] {
        background-color: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 12px 16px;
        box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
    }
    div[data-testid="stMetric"]:hover {
        border-color: #cbd5e1;
    }
    div[data-testid="stMetricLabel"] {
        font-size: 0.85rem !important;
        font-weight: 600 !important;
        color: #64748b !important;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.55rem !important;
        font-weight: 700 !important;
        color: #0f172a !important;
    }
    hr {
        margin: 1.5rem 0 !important;
        border-color: #f1f5f9 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def main():
    """Main application loop."""
    # 1. Initialize API Client
    client = SchemaGuardAPIClient()

    # 2. Check service health
    health_data = client.check_health()

    # 3. Render sidebar and get user page selection
    selected_page = render_sidebar(health_data, client.base_url)

    # 4. Route to selected view
    if selected_page == "Overview":
        render_overview_view(client)
    elif selected_page == "Pipeline Runs":
        render_pipeline_runs_view(client)
    elif selected_page == "Schema Evolution":
        render_schema_evolution_view(client)
    elif selected_page == "Quarantine Management":
        render_quarantine_view(client)
    elif selected_page == "Contract Explorer":
        render_contracts_view(client)
    elif selected_page == "Pipeline Trigger":
        render_execution_view(client)


if __name__ == "__main__":
    main()
