"""Step 6 (agentic alternative): chat with the connected data in plain English.

Claude answers each turn by exploring the schema and running SELECTs THROUGH
the deployed read-only MCP server, so it can never write. The conversation is
kept in session state and replayed to the backend so follow-ups have context
("...and how many of those are active?").
"""

import streamlit as st

from frontend.api_client import APIError, api_ask


def render_chat(active: dict) -> None:
    st.markdown('<div class="section-title">🤖 Chat with your data</div>', unsafe_allow_html=True)
    st.markdown(
        '<p class="section-sub">Ask questions in plain English and keep the conversation going. '
        '<b>Claude</b> explores the schema and runs <code>SELECT</code> queries <b>through your '
        'read-only MCP server</b> to answer — it cannot write, no matter what it generates.</p>',
        unsafe_allow_html=True,
    )

    # Chat history for THIS data source: list of {role, content, queries?}.
    chat = st.session_state.setdefault("chat", [])

    # Check if there is an automated question triggered from the Tables Overview.
    auto_ask = st.session_state.pop("auto_ask_question", None)
    if auto_ask:
        with st.spinner("Claude is exploring your data..."):
            try:
                history = [{"role": m["role"], "content": m["content"]} for m in chat[:-1]]
                ask = api_ask(active["deployment_id"], auto_ask, history)
                if ask.get("success"):
                    answer = ask.get("answer", "")
                    queries = ask.get("queries", [])
                    chat.append({"role": "assistant", "content": answer, "queries": queries})
                else:
                    message = ask.get("message", "The AI assistant is unavailable.")
                    st.error(message)
                    chat.pop()
            except Exception as exc:
                st.error(f"AI Assistant error: {exc}")
                chat.pop()

    if chat:
        col_hint, col_clear = st.columns([3, 1])
        col_hint.caption(f"💬 {sum(1 for m in chat if m['role'] == 'user')} question(s) this session")
        if col_clear.button("🧹  Clear chat", key="clear_chat", width="stretch"):
            st.session_state["chat"] = []
            st.rerun()

    # Replay the conversation so far.
    for msg in chat:
        with st.chat_message(msg["role"], avatar="🧑‍💻" if msg["role"] == "user" else "🤖"):
            st.markdown(msg["content"])
            if msg.get("queries"):
                with st.expander(f"🔎 SQL Claude ran ({len(msg['queries'])})", expanded=False):
                    for q in msg["queries"]:
                        st.code(q, language="sql")

    # A form keeps the input inline (not pinned to the viewport bottom) and clears
    # it on submit, so it plays nicely with the SQL panel below.
    with st.form("chat_form", clear_on_submit=True):
        question = st.text_input(
            "Your message",
            placeholder="e.g. How many tables are here? Then: which one has the most rows?",
            label_visibility="collapsed",
            key="chat_input",
        )
        sent = st.form_submit_button("✨  Send to Claude", width="stretch")

    if sent and question.strip():
        # Everything before this turn is the context we send to the backend.
        history = [{"role": m["role"], "content": m["content"]} for m in chat]
        chat.append({"role": "user", "content": question})
        with st.chat_message("user", avatar="🧑‍💻"):
            st.markdown(question)
        with st.chat_message("assistant", avatar="🤖"):
            with st.spinner("Claude is exploring your data..."):
                try:
                    ask = api_ask(active["deployment_id"], question, history)
                except APIError as exc:
                    ask = {"success": False, "message": str(exc)}
            if ask.get("success"):
                answer = ask.get("answer", "")
                queries = ask.get("queries", [])
                st.markdown(answer)
                if queries:
                    with st.expander(f"🔎 SQL Claude ran ({len(queries)})", expanded=False):
                        for q in queries:
                            st.code(q, language="sql")
                chat.append({"role": "assistant", "content": answer, "queries": queries})
            else:
                message = ask.get("message", "The AI assistant is unavailable.")
                st.info(message)
                # Keep the turn out of history on failure so a transient error
                # doesn't poison the context of later questions.
                chat.pop()
