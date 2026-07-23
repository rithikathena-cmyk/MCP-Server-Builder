import os
import socket
import sys
import threading
from urllib.parse import urlparse

import requests
import streamlit as st

# Make the project root importable so `backend` resolves when Streamlit runs
# this file from frontend/ (Streamlit puts frontend/ on sys.path, not the root).
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The frontend talks to the FastAPI backend (backend/api.py) over HTTP.
# Point MCP_API_URL at that service; defaults to a locally-running instance.
API_URL = os.environ.get("MCP_API_URL", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT = 30  # seconds — generous enough for connect + generate + deploy

_parsed = urlparse(API_URL)
API_HOST = _parsed.hostname or "127.0.0.1"
API_PORT = _parsed.port or 8000


def _api_is_up() -> bool:
    try:
        with socket.create_connection((API_HOST, API_PORT), timeout=0.4):
            return True
    except OSError:
        return False


# -------------------------------
# Page Configuration
# -------------------------------
st.set_page_config(
    page_title="MCP Server Builder",
    page_icon="🛠️",
    layout="centered",
    initial_sidebar_state="collapsed",
)


@st.cache_resource(show_spinner="Starting backend service...")
def _ensure_backend() -> str:
    """Start the FastAPI backend in-process (daemon thread) exactly once.

    Single-container hosting (e.g. Streamlit Community Cloud) runs only one
    process, so we launch uvicorn here instead of as a separate service. If a
    backend is already listening (local dev with a separate `uvicorn`), reuse
    it. `@st.cache_resource` guarantees this runs once per Streamlit server.
    """
    if _api_is_up():
        return "external"

    import time

    import uvicorn

    from backend.api import app as api_app

    def _run():
        # uvicorn skips signal handlers off the main thread, so this is safe.
        uvicorn.Server(
            uvicorn.Config(api_app, host="127.0.0.1", port=API_PORT, log_level="warning")
        ).run()

    threading.Thread(target=_run, daemon=True, name="mcp-backend").start()

    for _ in range(60):  # wait up to ~15s for the server to accept connections
        if _api_is_up():
            return "in-process"
        time.sleep(0.25)
    return "timeout"


# Ensure the backend is reachable before any API call (starts it in-process on
# single-container hosts; reuses an external uvicorn during local dev).
_ensure_backend()

# -------------------------------
# Enterprise Theme (custom CSS)
# -------------------------------
# Streamlit 1.56 only exposes a handful of [theme] keys in config.toml, so the
# richer look (brand header, cards, stepper, pill badges, button polish) is done
# here with scoped CSS targeting Streamlit's stable data-testid selectors.
st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

      :root {
        --brand:        #059669;
        --brand-2:      #0D9488;
        --brand-3:      #14B8A6;
        --brand-ink:    #064E3B;
        --ink:          #0F172A;
        --muted:        #64748B;
        --line:         #E7EAF0;
        --surface:      #FFFFFF;
        --surface-2:    #F8FAFC;
        --ok:           #16A34A;
        --ok-bg:        #F0FDF4;
        --err:          #DC2626;
        --err-bg:       #FEF2F2;
        --shadow-sm:    0 1px 2px rgba(15,23,42,.05);
        --shadow:       0 1px 3px rgba(15,23,42,.05), 0 12px 32px -8px rgba(15,23,42,.10);
        --shadow-lg:    0 24px 60px -16px rgba(6,78,59,.30);
      }

      html, body, [class*="css"], .stMarkdown, .stButton, input, textarea {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
        -webkit-font-smoothing: antialiased;
      }

      /* ---------- Ambient gradient-mesh background ---------- */
      [data-testid="stAppViewContainer"] {
        background: #F1F5F9;
      }
      [data-testid="stHeader"] { background: transparent; }
      #MainMenu, footer { visibility: hidden; }

      .block-container, [data-testid="stMainBlockContainer"] {
        max-width: 780px;
        padding-top: 2rem;
        padding-bottom: 4rem;
      }

      @keyframes rise { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
      @keyframes shimmer { 0% { background-position: -200% 0; } 100% { background-position: 200% 0; } }
      @keyframes pulse-ring {
        0%   { box-shadow: 0 0 0 0 rgba(5,150,105,.30); }
        70%  { box-shadow: 0 0 0 8px rgba(5,150,105,0); }
        100% { box-shadow: 0 0 0 0 rgba(5,150,105,0); }
      }

      /* ---------- Brand header (glass + sheen) ---------- */
      .app-header {
        position: relative; overflow: hidden;
        display: flex; align-items: center; gap: 16px;
        padding: 24px 26px;
        border-radius: 20px;
        background: linear-gradient(120deg, var(--brand) 0%, var(--brand-2) 55%, #0F766E 100%);
        color: #fff;
        box-shadow: var(--shadow-lg);
        animation: rise .5s ease both;
      }
      .app-header::after {
        content: ""; position: absolute; inset: 0;
        background: linear-gradient(100deg, transparent 30%, rgba(255,255,255,.22) 50%, transparent 70%);
        background-size: 200% 100%;
        animation: shimmer 6s linear infinite;
        pointer-events: none;
      }
      .app-header .logo {
        width: 52px; height: 52px; flex: 0 0 52px; position: relative; z-index: 1;
        display: grid; place-items: center;
        background: rgba(255,255,255,.18);
        border: 1px solid rgba(255,255,255,.3);
        border-radius: 14px; font-size: 26px;
        backdrop-filter: blur(6px);
      }
      .app-header .htext { position: relative; z-index: 1; }
      .app-header h1 { margin: 0; font-size: 1.5rem; font-weight: 800; letter-spacing: -.02em; }
      .app-header p  { margin: 3px 0 0; font-size: .88rem; opacity: .9; font-weight: 400; }
      .app-header .pill {
        position: relative; z-index: 1;
        margin-left: auto; font-size: .66rem; font-weight: 700; letter-spacing: .1em;
        text-transform: uppercase; padding: 7px 13px; border-radius: 999px;
        background: rgba(255,255,255,.2); border: 1px solid rgba(255,255,255,.35);
        backdrop-filter: blur(6px);
      }

      /* ---------- Trust badges row ---------- */
      .trust { display: flex; gap: 10px; flex-wrap: wrap; margin: 16px 2px 4px; animation: rise .6s ease both; }
      .trust .chip {
        display: inline-flex; align-items: center; gap: 7px;
        font-size: .78rem; font-weight: 600; color: #334155;
        background: rgba(255,255,255,.72); backdrop-filter: blur(8px);
        border: 1px solid var(--line); border-radius: 999px; padding: 7px 13px;
        box-shadow: var(--shadow-sm);
      }
      .trust .chip .ic { font-size: .9rem; }

      /* ---------- Stepper (connected + animated) ---------- */
      .stepper {
        display: flex; margin: 24px 4px 8px; padding: 0;
        animation: rise .6s ease both;
      }
      .stepper .step { flex: 1; text-align: center; position: relative; }
      /* connector line between dots */
      .stepper .step::before {
        content: ""; position: absolute; top: 17px; left: -50%; width: 100%; height: 3px;
        background: var(--line); z-index: 0; border-radius: 2px;
      }
      .stepper .step:first-child::before { display: none; }
      .stepper .step.done::before, .stepper .step.active::before {
        background: linear-gradient(90deg, var(--brand), var(--brand-2));
      }
      .stepper .dot {
        position: relative; z-index: 1;
        width: 34px; height: 34px; margin: 0 auto 9px; border-radius: 50%;
        display: grid; place-items: center; font-size: .82rem; font-weight: 700;
        background: #fff; color: var(--muted);
        border: 2px solid var(--line); transition: all .25s ease;
      }
      .stepper .label { font-size: .73rem; color: var(--muted); font-weight: 600; letter-spacing: .01em; }
      .stepper .step.done  .dot {
        background: linear-gradient(135deg, var(--brand), var(--brand-2));
        color:#fff; border-color: transparent;
      }
      .stepper .step.active .dot {
        background:#fff; color: var(--brand); border-color: var(--brand);
        animation: pulse-ring 1.6s ease-out infinite;
      }
      .stepper .step.done  .label, .stepper .step.active .label { color: var(--ink); }

      /* ---------- Section headings ---------- */
      .section-title {
        font-size: 1.1rem; font-weight: 700; color: var(--ink);
        margin: 28px 0 3px; letter-spacing: -.01em;
      }
      .section-sub { font-size: .86rem; color: var(--muted); margin: 0 0 6px; line-height: 1.5; }

      /* ---------- Form as an elevated glass card ---------- */
      [data-testid="stForm"] {
        background: rgba(255,255,255,.82);
        backdrop-filter: blur(10px);
        border: 1px solid rgba(255,255,255,.7);
        box-shadow: var(--shadow);
        border-radius: 20px;
        padding: 24px 26px 10px;
        animation: rise .6s ease both;
      }

      /* Inputs */
      [data-testid="stWidgetLabel"] p { font-weight: 600; font-size: .8rem; color: #475569; }
      .stTextInput input, .stNumberInput input {
        border-radius: 11px !important;
        border: 1px solid var(--line) !important;
        background: var(--surface-2) !important;
        padding: 11px 13px !important;
        transition: all .18s ease !important;
      }
      .stTextInput input:hover, .stNumberInput input:hover { border-color: #CBD5E1 !important; }
      .stTextInput input:focus, .stNumberInput input:focus {
        border-color: var(--brand) !important;
        box-shadow: 0 0 0 4px rgba(5,150,105,.15) !important;
        background: #fff !important;
      }
      [data-baseweb="select"] > div {
        border-radius: 11px !important;
        border: 1px solid var(--line) !important;
        background: var(--surface-2) !important;
      }

      /* Buttons */
      .stButton > button, [data-testid="stFormSubmitButton"] button {
        width: 100%;
        border-radius: 12px !important;
        font-weight: 700 !important;
        font-size: .95rem !important;
        letter-spacing: .01em !important;
        padding: 13px 16px !important;
        border: none !important;
        color: #fff !important;
        background: linear-gradient(120deg, var(--brand) 0%, var(--brand-2) 100%) !important;
        background-size: 160% 160% !important;
        box-shadow: 0 8px 20px -4px rgba(5,150,105,.5) !important;
        transition: transform .08s ease, box-shadow .25s ease, background-position .4s ease !important;
      }
      .stButton > button:hover, [data-testid="stFormSubmitButton"] button:hover {
        background-position: 100% 0 !important;
        box-shadow: 0 12px 28px -4px rgba(5,150,105,.6) !important;
        transform: translateY(-2px);
      }
      .stButton > button:active, [data-testid="stFormSubmitButton"] button:active {
        transform: translateY(0);
      }

      /* ---------- Result card + status badge ---------- */
      .result-card {
        background: rgba(255,255,255,.86); backdrop-filter: blur(10px);
        border: 1px solid var(--line);
        border-radius: 18px; padding: 20px 22px; box-shadow: var(--shadow);
        margin-top: 16px; animation: rise .45s ease both;
      }
      .badge {
        display: inline-flex; align-items: center; gap: 9px;
        font-size: .84rem; font-weight: 700; padding: 9px 15px; border-radius: 999px;
      }
      .badge .dotled { width: 9px; height: 9px; border-radius: 50%; }
      .badge.ok   { background: var(--ok-bg);  color: var(--ok);  }
      .badge.err  { background: var(--err-bg); color: var(--err); }
      .badge.idle { background: var(--surface-2); color: var(--muted); border: 1px solid var(--line); }
      .badge.ok   .dotled { background: var(--ok);  box-shadow: 0 0 0 4px rgba(22,163,74,.16); animation: pulse-ring 2s infinite; }
      .badge.err  .dotled { background: var(--err); box-shadow: 0 0 0 4px rgba(220,38,38,.16); }
      .badge.idle .dotled { background: #94A3B8; }

      .kv { font-size: .84rem; color: var(--muted); margin: 12px 0 0; line-height: 1.7; }
      .kv code {
        background: var(--surface-2); border: 1px solid var(--line);
        border-radius: 7px; padding: 3px 8px; color: var(--brand-ink);
        font-size: .8rem; font-weight: 600;
      }

      /* ---------- Footer ---------- */
      .app-footer {
        text-align: center; margin-top: 34px; padding-top: 18px;
        border-top: 1px solid var(--line);
        font-size: .76rem; color: var(--muted);
      }
      .app-footer b { color: #475569; font-weight: 700; }
    </style>
    """,
    unsafe_allow_html=True,
)

# -------------------------------
# Stepper (live progress indicator)
# -------------------------------
STEPS = ["Connect", "Test", "Generate", "Deploy", "Register", "Query"]


def render_stepper(slot, active: int):
    """Render the 6-stage progress stepper into `slot`.

    Steps before `active` render as done, the one at `active` is highlighted.
    """
    cells = []
    for i, name in enumerate(STEPS):
        state = "done" if i < active else ("active" if i == active else "")
        mark = "✓" if i < active else str(i + 1)
        cells.append(
            f'<div class="step {state}">'
            f'<div class="dot">{mark}</div>'
            f'<div class="label">{name}</div>'
            f'</div>'
        )
    slot.markdown(f'<div class="stepper">{"".join(cells)}</div>', unsafe_allow_html=True)


# -------------------------------
# Backend API client
# -------------------------------
class APIError(Exception):
    """Raised when the FastAPI backend is unreachable or returns an error."""


def _post(path: str, json: dict | None = None):
    try:
        resp = requests.post(f"{API_URL}{path}", json=json, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError as exc:
        raise APIError(
            f"Cannot reach the API at {API_URL}. Start it with:\n"
            "    uvicorn backend.api:app --port 8000 --reload"
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise APIError(f"API request failed: {exc}") from exc


def api_test_connection(config: dict) -> dict:
    return _post("/api/test-connection", config)


def api_deploy(config: dict) -> dict:
    return _post("/api/deploy", config)


def api_register(deployment_id: str) -> dict:
    return _post(f"/api/register/{deployment_id}")


def api_query(deployment_id: str, sql: str) -> dict:
    return _post("/api/query", {"deployment_id": deployment_id, "sql": sql})


def api_ask(deployment_id: str, question: str) -> dict:
    return _post("/api/ask", {"deployment_id": deployment_id, "question": question})


# -------------------------------
# Brand header
# -------------------------------
st.markdown(
    """
    <div class="app-header">
      <div class="logo">🛠️</div>
      <div class="htext">
        <h1>MCP Server Builder</h1>
        <p>Generate a secure, read-only MCP server from any SQL database</p>
      </div>
      <div class="pill">Enterprise</div>
    </div>
    <div class="trust">
      <span class="chip"><span class="ic">🔒</span> Read-only by design</span>
      <span class="chip"><span class="ic">🛡️</span> SQL-validated queries</span>
      <span class="chip"><span class="ic">🚫</span> Credentials never stored</span>
      <span class="chip"><span class="ic">⚡</span> Deploys in seconds</span>
    </div>
    """,
    unsafe_allow_html=True,
)

stepper_slot = st.empty()

active = st.session_state.get("active")


def _run_build(config: dict):
    """Steps 3-5: generate, deploy, and register — with a live stepper."""
    render_stepper(stepper_slot, active=2)
    progress = st.progress(0, text="Generating MCP server...")
    progress.progress(35, text="Generating MCP server...")
    render_stepper(stepper_slot, active=3)

    try:
        with st.spinner("Generating and deploying MCP server..."):
            deploy = api_deploy(config)
    except APIError as exc:
        progress.empty()
        st.code(str(exc))
        st.stop()

    if not deploy.get("running"):
        progress.empty()
        st.markdown(
            '<div class="result-card">'
            '<span class="badge err"><span class="dotled"></span>Server Failed to Start</span>'
            f'<p class="kv">Generated file: <code>{deploy.get("server_path", "")}</code></p>'
            '</div>',
            unsafe_allow_html=True,
        )
        if deploy.get("log"):
            st.code(deploy["log"])
        st.stop()

    progress.progress(70, text="Registering with host application...")
    render_stepper(stepper_slot, active=4)
    try:
        with st.spinner("Registering server with host application..."):
            registration = api_register(deploy["deployment_id"])
    except APIError as exc:
        progress.empty()
        st.code(str(exc))
        st.stop()

    progress.progress(100, text="Ready")
    progress.empty()
    render_stepper(stepper_slot, active=5)

    st.session_state["active"] = {
        "deployment_id": deploy["deployment_id"],
        "server_name": deploy.get("server_name", ""),
        "server_path": deploy.get("server_path", ""),
        "url": deploy.get("url", ""),
        "database": config["database"],
        "db_type": config["db_type"],
        "host": config["host"],
        "port": config["port"],
        "username": config["username"],
        "config_text": registration.get("config_text", ""),
    }
    st.session_state["query_result"] = None
    st.session_state["ask_result"] = None
    st.session_state.pop("test", None)


# ================================================================
# SUCCESS SCREEN — a connected data source is active (steps 5 & 6)
# ================================================================
if active:
    render_stepper(stepper_slot, active=5)

    st.markdown(
        """
        <style>
          .success-hero {
            position: relative; overflow: hidden; text-align: center;
            border-radius: 20px; padding: 30px 26px 26px; margin-top: 6px;
            background: linear-gradient(135deg, #ECFDF5 0%, #F0FDFA 100%);
            border: 1px solid #A7F3D0; box-shadow: var(--shadow);
            animation: rise .5s ease both;
          }
          .success-hero .check {
            width: 60px; height: 60px; margin: 0 auto 12px; border-radius: 50%;
            display: grid; place-items: center; font-size: 30px; color: #fff;
            background: linear-gradient(135deg, #16A34A, #059669);
            box-shadow: 0 8px 22px -4px rgba(5,150,105,.5);
            animation: pulse-ring 2s infinite;
          }
          .success-hero h2 { margin: 0; font-size: 1.4rem; font-weight: 800; color: #065F46; letter-spacing: -.02em; }
          .success-hero p  { margin: 6px 0 0; font-size: .9rem; color: #047857; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="success-hero">
          <div class="check">✓</div>
          <h2>Your data source is connected</h2>
          <p><b>{active["database"]}</b> ({active["db_type"]}) is live, registered, and ready for read-only queries.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="result-card">'
        '<span class="badge ok"><span class="dotled"></span>Server Running &amp; Registered</span>'
        f'<p class="kv">'
        f'MCP endpoint: <code>{active["url"]}</code><br>'
        f'Generated file: <code>{active["server_path"]}</code></p>'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- Step 5: host-application registration snippet ---
    with st.expander("🔌  Host application registration", expanded=False):
        st.caption(
            "This server is registered and persisted to `generated_servers/registry.json`. "
            "Add the snippet below to your host application (e.g. Claude Desktop) to use it there."
        )
        st.code(active["config_text"], language="json")

    # --- Agentic: ask your data in plain English (Claude uses the MCP server) ---
    st.markdown('<div class="section-title">🤖 Ask your data</div>', unsafe_allow_html=True)
    st.markdown(
        '<p class="section-sub">Ask a question in plain English. <b>Claude</b> explores the '
        'schema and runs <code>SELECT</code> queries <b>through your read-only MCP server</b> '
        'to answer — it cannot write, no matter what it generates.</p>',
        unsafe_allow_html=True,
    )
    question = st.text_input(
        "Your question",
        placeholder="e.g. How many tables are in this database, and which has the most rows?",
        key="ask_input",
    )
    if st.button("✨  Ask Claude", key="ask_btn"):
        if question.strip():
            try:
                with st.spinner("Claude is exploring your data..."):
                    st.session_state["ask_result"] = api_ask(active["deployment_id"], question)
            except APIError as exc:
                st.session_state["ask_result"] = {"success": False, "message": str(exc)}

    ask = st.session_state.get("ask_result")
    if ask is not None:
        if ask.get("success"):
            st.markdown(
                '<div class="result-card">'
                '<span class="badge ok"><span class="dotled"></span>Answer</span></div>',
                unsafe_allow_html=True,
            )
            st.markdown(ask.get("answer", ""))
            if ask.get("queries"):
                with st.expander(f"🔎 SQL Claude ran ({len(ask['queries'])})", expanded=False):
                    for q in ask["queries"]:
                        st.code(q, language="sql")
        else:
            st.info(ask.get("message", "The AI assistant is unavailable."))

    # --- Step 6: run read-only queries through the new server ---
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
        try:
            _post(f"/api/stop/{active['deployment_id']}")
        except APIError:
            pass
        st.session_state["active"] = None
        st.session_state["query_result"] = None
        st.session_state["ask_result"] = None
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
        st.session_state["ask_result"] = None
        st.rerun()

# ================================================================
# WIZARD — collect params, Test Connection, then Build & Connect
# ================================================================
else:
    test = st.session_state.get("test")
    render_stepper(stepper_slot, active=1 if (test and test.get("ok")) else 0)

    st.markdown('<div class="section-title">Connect a Database</div>', unsafe_allow_html=True)
    st.markdown(
        '<p class="section-sub">Enter your database details and test the connection. '
        'Your password is masked and never stored on disk — it is used only to validate '
        'access with a single read-only <code>SELECT&nbsp;1</code>.</p>',
        unsafe_allow_html=True,
    )

    DEFAULT_PORTS = {"MySQL": 3306, "PostgreSQL": 5432, "TiDB": 4000, "SQL Server": 1433}
    HOST_HINTS = {
        "MySQL": "127.0.0.1  or  aws.connect.psdb.cloud",
        "PostgreSQL": "127.0.0.1  or  <project>.neon.tech",
        "TiDB": "gateway01.<region>.prod.aws.tidbcloud.com",
        "SQL Server": "127.0.0.1",
    }

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

    if db_type == "TiDB":
        st.caption(
            "💡 **TiDB Cloud Serverless (free):** open your cluster → **Connect**, copy the "
            "Host, Port `4000`, User & Password. Keep **🔒 SSL** checked — TiDB Cloud requires TLS."
        )

    database = st.text_input("Database Name", placeholder="test", key="in_database")

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
        "database": database,
        "username": username,
        "password": password,
        "ssl": bool(use_ssl),
    }
    # Signature identifies THIS exact set of inputs, so an earlier "tested OK"
    # result is invalidated the moment any field is edited.
    signature = "|".join(
        str(config[k]) for k in ("db_type", "host", "port", "database", "username", "password", "ssl")
    )
    tested_ok = bool(test and test.get("ok") and test.get("sig") == signature)

    missing = [
        label for label, val in
        [("Host", host), ("Database name", database), ("User ID", username), ("Password", password)]
        if not val
    ]

    col_test, col_build = st.columns(2)
    test_clicked = col_test.button("🔌  Test Connection", key="btn_test", use_container_width=True)
    build_clicked = col_build.button(
        "🚀  Build & Connect", key="btn_build", use_container_width=True, disabled=not tested_ok
    )

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
                f'<p class="kv">Reachable: <code>{database}</code> on '
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
        _run_build(config)
        st.balloons()
        st.rerun()

    render_status()

# -------------------------------
# Footer
# -------------------------------
st.markdown(
    '<div class="app-footer">Built with <b>FastMCP</b> &amp; <b>SQLAlchemy</b> '
    '&middot; Read-only MCP servers for MySQL, PostgreSQL, TiDB &amp; SQL Server</div>',
    unsafe_allow_html=True,
)
