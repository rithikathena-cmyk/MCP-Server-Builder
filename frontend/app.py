"""Streamlit UI for the MCP Server Builder — a six-step wizard that connects a
SQL database and exposes it through a generated, read-only MCP server.

See README.md for the full flow. Each piece of the UI lives in its own module:
  - theme.py                       — CSS
  - stepper.py                     — the 6-stage progress indicator
  - api_client.py                  — HTTP calls to the backend + its bootstrap
  - steps/connect_form.py          — steps 1-2 (collect + test credentials)
  - steps/build_flow.py            — steps 3-5 (generate, deploy, register)
  - steps/dashboard.py             — steps 5-6 success screen (tables/chat/query)
"""

import os
import sys

import streamlit as st

# Make the project root importable so `backend`/`mcp_server`/`frontend.*` resolve
# when Streamlit runs this file from frontend/ (Streamlit puts frontend/ on
# sys.path, not the root).
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

st.set_page_config(
    page_title="MCP Server Builder",
    page_icon="🛠️",
    layout="centered",
    initial_sidebar_state="collapsed",
)

from frontend import theme
from frontend.api_client import bridge_secrets_to_env, ensure_backend
from frontend.steps.connect_form import render_connect_form
from frontend.steps.dashboard import render_dashboard

# Bridge Streamlit secrets -> process environment, then start (or reuse) the
# backend, before any API call is made.
bridge_secrets_to_env()
ensure_backend()

theme.inject_base_theme()

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

if active:
    render_dashboard(active, stepper_slot)
else:
    render_connect_form(stepper_slot)

# -------------------------------
# Footer
# -------------------------------
st.markdown(
    '<div class="app-footer">Built with <b>FastMCP</b> &amp; <b>SQLAlchemy</b> '
    '&middot; Read-only MCP servers for MySQL, PostgreSQL, TiDB &amp; SQL Server</div>',
    unsafe_allow_html=True,
)
