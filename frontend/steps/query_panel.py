"""Step 6: run manual read-only SQL through the deployed MCP server, plus the
write-refusal demo and the disconnect control."""

import streamlit as st

from frontend.api_client import APIError, api_query, api_stop


def render_query_panel(active: dict) -> None:
    st.markdown('<div class="section-title">Query your data</div>', unsafe_allow_html=True)
    st.markdown(
        '<p class="section-sub">Queries run <b>through the deployed MCP server</b>. '
        'This server is read-only — <code>INSERT</code>, <code>UPDATE</code> and '
        '<code>DELETE</code> are refused.</p>',
        unsafe_allow_html=True,
    )

    default_sql = f"SELECT * FROM information_schema.tables\nWHERE table_schema = '{active['database']}'\nLIMIT 10;"
    sql = st.text_area("SQL (SELECT only)", value=default_sql, height=110, key="sql_input")

    col_run, col_write, col_stop = st.columns([1, 1, 1])
    run_clicked = col_run.button("▶  Run Query", key="run_query")
    write_clicked = col_write.button("⛔  Test a Write", key="test_write")
    stop_clicked = col_stop.button("⏹  Disconnect", key="stop_server")

    if run_clicked:
        try:
            with st.spinner("Running query through the MCP server..."):
                st.session_state["query_result"] = api_query(active["deployment_id"], sql)
        except APIError as exc:
            st.code(str(exc))

    if write_clicked:
        # Demonstrate write-refusal end to end: send an UPDATE and show the refusal.
        demo = f"UPDATE {active['database']}.some_table SET x = 1"
        try:
            with st.spinner("Attempting a write (expected to be refused)..."):
                st.session_state["query_result"] = api_query(active["deployment_id"], demo)
        except APIError as exc:
            st.code(str(exc))

    if stop_clicked:
        api_stop(active["deployment_id"])
        st.session_state["active"] = None
        st.session_state["query_result"] = None
        st.session_state["chat"] = []
        st.rerun()

    result = st.session_state.get("query_result")
    if result is not None:
        if result.get("success"):
            rows = result.get("rows", [])
            st.markdown(
                '<div class="result-card">'
                '<span class="badge ok"><span class="dotled"></span>Query OK</span>'
                f'<p class="kv">{result.get("row_count", len(rows))} row(s) returned</p>'
                '</div>',
                unsafe_allow_html=True,
            )
            if rows:
                st.dataframe(rows, use_container_width=True)
        else:
            st.markdown(
                '<div class="result-card">'
                '<span class="badge err"><span class="dotled"></span>Refused / Error</span>'
                '</div>',
                unsafe_allow_html=True,
            )
            st.code(result.get("message", "Unknown error"))

    st.divider()
    if st.button("＋  Connect another data source", key="connect_another"):
        st.session_state["active"] = None
        st.session_state["query_result"] = None
        st.session_state["chat"] = []
        st.rerun()
