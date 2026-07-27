"""The success screen shown once a data source is connected (steps 5-6)."""

import streamlit as st

from frontend.stepper import render_stepper
from frontend.steps.chat import render_chat
from frontend.steps.query_panel import render_query_panel
from frontend.steps.tables_overview import render_tables_overview

_SUCCESS_CSS = """
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
"""


def render_dashboard(active: dict, stepper_slot) -> None:
    render_stepper(stepper_slot, active=5)

    st.markdown(_SUCCESS_CSS, unsafe_allow_html=True)
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

    render_tables_overview(active)
    render_chat(active)
    render_query_panel(active)
