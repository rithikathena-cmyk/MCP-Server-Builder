"""Steps 1-2 of the wizard: collect connection parameters and test them."""

import streamlit as st

from frontend.api_client import APIError, api_discover_schemas, api_test_connection
from frontend.stepper import render_stepper
from frontend.steps.build_flow import run_build

DEFAULT_PORTS = {"MySQL": 3306, "PostgreSQL": 5432, "TiDB": 4000, "SQL Server": 1433}
HOST_HINTS = {
    "MySQL": "127.0.0.1  or  aws.connect.psdb.cloud",
    "PostgreSQL": "127.0.0.1  or  <project>.neon.tech",
    "TiDB": "gateway01.<region>.prod.aws.tidbcloud.com",
    "SQL Server": "127.0.0.1",
}


def render_connect_form(stepper_slot) -> None:
    test = st.session_state.get("test")
    render_stepper(stepper_slot, active=1 if (test and test.get("ok")) else 0)

    st.markdown('<div class="section-title">Connect a Database</div>', unsafe_allow_html=True)
    st.markdown(
        '<p class="section-sub">Enter your database details and test the connection. '
        'Your password is masked and never stored on disk — it is used only to validate '
        'access with a single read-only <code>SELECT&nbsp;1</code>.</p>',
        unsafe_allow_html=True,
    )

    db_type = st.selectbox("Database Type", list(DEFAULT_PORTS), key="in_db_type")

    # Snap the port to the selected engine's conventional default whenever the
    # database type changes (TiDB Cloud uses 4000, not 3306).
    if st.session_state.get("_prev_db_type") != db_type:
        st.session_state["_prev_db_type"] = db_type
        st.session_state["in_port"] = DEFAULT_PORTS[db_type]

    col_host, col_port = st.columns([3, 1])
    with col_host:
        host = st.text_input("Host / IP Address", placeholder=HOST_HINTS[db_type], key="in_host")
    with col_port:
        port = st.number_input("Port", min_value=1, max_value=65535, step=1, key="in_port")

    col_user, col_pass = st.columns(2)
    with col_user:
        username = st.text_input("User ID", key="in_username")
    with col_pass:
        password = st.text_input("Password", type="password", key="in_password")

    use_ssl = st.checkbox(
        "🔒  Require SSL/TLS",
        value=True,
        key="in_ssl",
        help="Needed for cloud databases: PlanetScale, TiDB Cloud, Neon, Supabase. "
             "Uncheck only for a plain local database without TLS.",
    )

    config = {
        "db_type": db_type,
        "host": host,
        "port": int(port),
        "username": username,
        "password": password,
        "ssl": bool(use_ssl),
    }
    # Signature identifies THIS exact set of inputs, so an earlier "tested OK"
    # result is invalidated the moment any field is edited.
    signature = "|".join(
        str(config.get(k, "")) for k in ("db_type", "host", "port", "database", "username", "password", "ssl")
    )
    tested_ok = bool(test and test.get("ok") and test.get("sig") == signature)

    missing = [
        label for label, val in
        [("Host", host), ("User ID", username), ("Password", password)]
        if not val
    ]

    col_test, col_build = st.columns(2)
    test_clicked = col_test.button("🔌  Test Connection", key="btn_test", use_container_width=True)
    build_clicked = col_build.button(
        "🚀  Build & Connect", key="btn_build", use_container_width=True, disabled=not tested_ok
    )

    # After a successful test, discover available schemas
    if test and test.get("ok") and not st.session_state.get("schemas_fetched"):
        with st.spinner("Discovering databases..."):
            schemas, error = api_discover_schemas(config)
            if schemas:
                st.session_state["available_schemas"] = schemas
                st.session_state["selected_schema"] = schemas[0]
            elif error:
                st.error(f"Failed to discover databases: {error}")
            else:
                st.error("No databases found on the server.")
        st.session_state["schemas_fetched"] = True

    # If schemas are available, show a selector
    if st.session_state.get("available_schemas"):
        selected = st.selectbox("Select Database", st.session_state["available_schemas"], key="in_selected_schema")
        config["database"] = selected

    # --- Live status indicator (persists across reruns) ---
    status_slot = st.empty()

    def render_status():
        if not test or test.get("sig") != signature:
            status_slot.markdown(
                '<div class="result-card"><span class="badge idle">'
                '<span class="dotled"></span>Not tested yet — run <b>Test Connection</b> to verify access</span>'
                '</div>',
                unsafe_allow_html=True,
            )
        elif test.get("ok"):
            status_slot.markdown(
                '<div class="result-card">'
                '<span class="badge ok"><span class="dotled"></span>Connection verified — ready to build</span>'
                f'<p class="kv">Reachable: <code>{config.get("database", "<none>")}</code> on '
                f'<code>{host}:{port}</code> as <code>{username}</code> &middot; <code>{db_type}</code></p>'
                '</div>',
                unsafe_allow_html=True,
            )
        else:
            status_slot.markdown(
                '<div class="result-card">'
                '<span class="badge err"><span class="dotled"></span>Connection failed — check details and try again</span>'
                '</div>',
                unsafe_allow_html=True,
            )
            st.code(test.get("message", "Unknown error"))

    if test_clicked:
        if missing:
            st.warning("Please fill in: " + ", ".join(missing))
        else:
            render_stepper(stepper_slot, active=1)
            try:
                with st.spinner("Testing database connection..."):
                    result = api_test_connection(config)
            except APIError as exc:
                st.session_state["test"] = {"ok": False, "message": str(exc), "sig": signature}
                st.rerun()
            st.session_state["test"] = {
                "ok": bool(result["success"]),
                "message": result["message"],
                "sig": signature,
            }
            st.rerun()

    if build_clicked and tested_ok:
        run_build(stepper_slot, config)
        st.balloons()
        st.rerun()

    render_status()
