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
    # result is invalidated the moment any field is edited. Database selection
    # is deliberately excluded — it's chosen from an already-verified server,
    # so changing it doesn't require re-testing the connection.
    signature = "|".join(
        str(config.get(k, "")) for k in ("db_type", "host", "port", "username", "password", "ssl")
    )
    tested_ok = bool(test and test.get("ok") and test.get("sig") == signature)

    missing = [
        label for label, val in
        [("Host", host), ("User ID", username), ("Password", password)]
        if not val
    ]

    supports_multi_db = db_type in ("MySQL", "TiDB")
    available_schemas = st.session_state.get("available_schemas", [])
    # Read back last run's widget value (if any) so the build button's
    # disabled state reflects the current selection even though the
    # multiselect widget itself is drawn further down the page.
    selected_databases = st.session_state.get("in_selected_databases") or (
        available_schemas[:1] if available_schemas else []
    )
    build_disabled = not tested_ok or not selected_databases

    col_test, col_build = st.columns(2)
    test_clicked = col_test.button("🔌  Test Connection", key="btn_test", width="stretch")
    build_clicked = col_build.button(
        "🚀  Build & Connect", key="btn_build", width="stretch", disabled=build_disabled
    )

    # After a successful test, discover available schemas
    if test and test.get("ok") and not st.session_state.get("schemas_fetched"):
        with st.spinner("Discovering databases..."):
            schemas, error = api_discover_schemas(config)
            if schemas:
                st.session_state["available_schemas"] = schemas
            elif error:
                st.error(f"Failed to discover databases: {error}")
            else:
                st.error("No databases found on the server.")
        st.session_state["schemas_fetched"] = True

    # If schemas are available, let the user pick one or more. MySQL/TiDB can
    # query across every database selected here in the same deployment;
    # PostgreSQL/SQL Server are capped to exactly one.
    if st.session_state.get("available_schemas"):
        selected = st.multiselect(
            "Select Database(s)" if supports_multi_db else "Select Database",
            st.session_state["available_schemas"],
            default=st.session_state["available_schemas"][:1],
            max_selections=None if supports_multi_db else 1,
            key="in_selected_databases",
            help=(
                "Pick more than one to query across databases in the same chat/query "
                "session — every SQL reference must then be fully qualified as "
                "database.table." if supports_multi_db else
                f"{db_type} connections are scoped to exactly one database."
            ),
        )
        config["databases"] = selected

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
            databases_label = ", ".join(config.get("databases", [])) or "<none selected>"
            status_slot.markdown(
                '<div class="result-card">'
                '<span class="badge ok"><span class="dotled"></span>Connection verified — ready to build</span>'
                f'<p class="kv">Reachable: <code>{databases_label}</code> on '
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

    if build_clicked and tested_ok and config.get("databases"):
        run_build(stepper_slot, config)
        st.balloons()
        st.rerun()

    render_status()
