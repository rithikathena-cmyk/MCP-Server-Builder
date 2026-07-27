"""Steps 3-5 of the wizard: generate, deploy, and register the MCP server."""

import streamlit as st

from frontend.api_client import APIError, api_deploy, api_register
from frontend.stepper import render_stepper


def run_build(stepper_slot, config: dict) -> None:
    """Generate, deploy, and register — with a live stepper.

    Leaves the built deployment in `st.session_state["active"]` on success.
    """
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
        "databases": config["databases"],
        "db_type": config["db_type"],
        "host": config["host"],
        "port": config["port"],
        "username": config["username"],
        "config_text": registration.get("config_text", ""),
    }
    st.session_state["query_result"] = None
    st.session_state["chat"] = []
    st.session_state.pop("test", None)
