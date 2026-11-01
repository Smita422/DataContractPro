"""Data Contract Explorer View."""

import streamlit as st

from schemaguard.dashboard.api_client import SchemaGuardAPIClient
from schemaguard.dashboard.components.tables import render_columns_definition_table


def render_contracts_view(client: SchemaGuardAPIClient) -> None:
    """Render the data contract exploration and schema specification view."""
    st.markdown("## 📜 Data Contract Explorer")
    st.markdown(
        "Inspect declarative YAML data contracts, schema definitions, semantic constraints, and derived expressions."
    )

    # 1. Fetch available datasets & versions
    contracts_meta = client.list_contracts()
    datasets_map = contracts_meta.get("datasets", {})

    if not datasets_map:
        st.warning("No data contracts registered in the system.")
        return

    col1, col2 = st.columns(2)
    with col1:
        selected_dataset = st.selectbox(
            "Select Dataset",
            list(datasets_map.keys()),
            index=0,
        )
    with col2:
        available_versions = datasets_map.get(selected_dataset, ["1.0.0"])
        selected_version = st.selectbox(
            "Contract Version",
            available_versions,
            index=len(available_versions) - 1,  # Default to latest
        )

    # 2. Fetch specific contract details
    contract = client.get_contract(selected_dataset, selected_version)
    if not contract:
        st.error(f"Could not load contract for dataset `{selected_dataset}` v`{selected_version}`.")
        return

    # Metadata Header
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Dataset", contract.get("dataset"))
    with m2:
        st.metric("Semantic Version", f"v{contract.get('version')}")
    with m3:
        st.metric("Owner", contract.get("owner"))
    with m4:
        st.metric("Compatibility Mode", contract.get("compatibility_mode"))

    if contract.get("description"):
        st.caption(f"**Description:** {contract.get('description')}")

    st.markdown("---")

    # 3. Columns Definition Table
    st.markdown("### 🏛️ Schema Columns & Semantic Constraints")
    columns = contract.get("columns", [])
    render_columns_definition_table(columns)

    # 4. Derived Fields
    derived_fields = contract.get("derived_fields", [])
    if derived_fields:
        st.markdown("### 🧮 Derived Computational Fields")
        derived_data = []
        for df in derived_fields:
            derived_data.append({
                "Field Name": df.get("name"),
                "Type": df.get("type"),
                "Formula / Expression": f"`{df.get('expression')}`",
                "Description": df.get("description") or "-",
            })
        st.dataframe(derived_data, use_container_width=True, hide_index=True)

    # 5. Version Comparison (if multiple versions exist)
    if len(available_versions) > 1:
        st.markdown("---")
        st.markdown("### ⚖️ Contract Version Evolution Comparison")
        st.caption(f"Comparing versions for dataset: `{selected_dataset}`")
        comp_v1, comp_v2 = st.columns(2)
        with comp_v1:
            st.markdown(f"**Version {available_versions[0]} Columns:**")
            c1_detail = client.get_contract(selected_dataset, available_versions[0])
            c1_cols = [c["name"] for c in c1_detail.get("columns", [])] if c1_detail else []
            st.code("\n".join(c1_cols) or "None", language="text")
        with comp_v2:
            st.markdown(f"**Version {available_versions[-1]} Columns:**")
            c2_detail = client.get_contract(selected_dataset, available_versions[-1])
            c2_cols = [c["name"] for c in c2_detail.get("columns", [])] if c2_detail else []
            st.code("\n".join(c2_cols) or "None", language="text")

        added_cols = set(c2_cols) - set(c1_cols)
        removed_cols = set(c1_cols) - set(c2_cols)
        if added_cols:
            st.success(f"Added in v{available_versions[-1]}: `{', '.join(added_cols)}` (Non-breaking optional evolution)")
        if removed_cols:
            st.error(f"Removed in v{available_versions[-1]}: `{', '.join(removed_cols)}`")
