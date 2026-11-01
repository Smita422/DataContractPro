"""Sidebar navigation and connection status component."""

from datetime import datetime, timezone
from typing import Dict, Any
import streamlit as st

PAGE_OPTIONS = [
    "Overview",
    "Pipeline Runs",
    "Schema Evolution",
    "Quarantine Management",
    "Contract Explorer",
    "Pipeline Trigger",
]


def render_sidebar(health_data: Dict[str, Any], api_url: str) -> str:
    """Render the application sidebar with branding, navigation, and API status."""
    st.sidebar.markdown(
        """
        <div style="padding: 10px 0 20px 0;">
            <h1 style="font-size: 1.6rem; font-weight: 700; margin-bottom: 2px; color: #1e293b;">
                🛡️ SchemaGuard
            </h1>
            <p style="font-size: 0.85rem; color: #64748b; margin: 0; line-height: 1.3;">
                Data Contract Validation &amp; Schema Evolution Platform
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # API Connection Indicator
    is_connected = health_data.get("is_available", False)
    if is_connected:
        st.sidebar.success(f"🟢 **API Online** ({health_data.get('version', 'v0.1.0')})")
    else:
        st.sidebar.error("🔴 **API Disconnected**")
        st.sidebar.caption(f"Cannot reach `{api_url}`. Start FastAPI backend with `uvicorn schemaguard.api.main:app`.")

    st.sidebar.markdown("---")

    # Navigation menu
    selected_page = st.sidebar.radio(
        "Navigation",
        PAGE_OPTIONS,
        index=0,
        label_visibility="collapsed",
    )

    st.sidebar.markdown("---")

    # Refresh control and timestamp
    if st.sidebar.button("🔄 Refresh Data", use_container_width=True):
        st.session_state["last_refresh"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        st.rerun()

    last_refresh = st.session_state.get("last_refresh")
    if not last_refresh:
        last_refresh = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        st.session_state["last_refresh"] = last_refresh

    st.sidebar.caption(f"Last Refreshed:\n`{last_refresh}`")
    st.sidebar.caption(f"Backend: `{api_url}`")

    return selected_page
