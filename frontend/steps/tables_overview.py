"""Table browser shown on the success screen: pick a table, see a sample."""

import streamlit as st

from frontend.api_client import api_query, fetch_tables


def render_tables_overview(active: dict) -> None:
    if "tables" not in active:
        with st.spinner("Discovering database tables..."):
            active["tables"] = fetch_tables(active["deployment_id"], active["db_type"], active["databases"])

    tables = active.get("tables", [])
    if not tables:
        return

    st.markdown('<div class="section-title">📋 Database Tables Overview</div>', unsafe_allow_html=True)
    st.markdown(
        '<p class="section-sub">Select any table to read its schema / sample data and quickly ask the AI questions about it.</p>',
        unsafe_allow_html=True,
    )

    col_sel, col_action = st.columns([3, 1])
    selected_table = col_sel.selectbox("Select table:", tables, label_visibility="collapsed", key="inspect_table")

    if not selected_table:
        return

    if col_action.button("💬 Ask about table", key=f"ask_btn_{selected_table}", use_container_width=True):
        question_to_ask = (
            f"Analyze the table '{selected_table}'. List its columns and explain what "
            "kind of data is stored in it based on the first few rows."
        )
        st.session_state["auto_ask_question"] = question_to_ask
        if "chat" not in st.session_state:
            st.session_state["chat"] = []
        st.session_state["chat"].append({"role": "user", "content": question_to_ask})
        st.rerun()

    sample_sql = f"SELECT * FROM {selected_table} LIMIT 5;"
    try:
        res = api_query(active["deployment_id"], sample_sql)
        if res.get("success"):
            rows = res.get("rows", [])
            if rows:
                st.dataframe(rows, use_container_width=True)
            else:
                st.info(f"Table '{selected_table}' is empty (no rows returned).")
        else:
            st.error(f"Could not read table '{selected_table}': {res.get('message', 'Unknown error')}")
    except Exception as e:
        st.error(f"Error reading table: {e}")
