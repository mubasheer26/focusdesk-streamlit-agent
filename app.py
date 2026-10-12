"""Local FocusDesk chat UI. Run: python -m streamlit run app.py."""

import json
import os
import urllib.request
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

import task_agent as agent


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
MODEL = os.getenv("FOCUSDESK_MODEL", "qwen3:4b")
DB = Path(os.getenv("FOCUSDESK_DB", "data/tasks.db"))
if not DB.is_absolute():
    DB = ROOT / DB

st.set_page_config(page_title="FocusDesk | Your task companion", page_icon="✓", layout="wide")
st.markdown("""<style>
.stApp {background: #f5f7fb;}
.block-container {max-width: 1250px; padding-top: 2.2rem;}
h1, h2, h3 {color: #142b45;}
[data-testid="stChatMessage"] {background: white; border: 1px solid #e0e7ef; border-radius: 16px;}
[data-testid="stSidebar"] {background: #eaf0f7;}
</style>""", unsafe_allow_html=True)

if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "system", "content": agent.SYSTEM}]
    st.session_state.turns = []

store = agent.TaskStore(DB)


def render_events(events):
    """Only show observable tool activity, never hidden model reasoning."""
    for event in events:
        if event["kind"] == "tool_start":
            call = event.get("call")
            function = call.get("function", {}) if isinstance(call, dict) else {}
            if not isinstance(function, dict):
                function = {}
            st.write(f"Calling {function.get('name', 'unknown tool')}…")
            st.json(function.get("arguments", {}), expanded=False)
        elif event["kind"] == "tool_result":
            result = event["result"]
            st.write(f"{event['name']}: {result.get('status', result.get('error', 'finished'))}")
            st.json(result, expanded=False)


with st.sidebar:
    st.title("FocusDesk")
    st.caption("Your tasks. On your computer.")
    st.divider()
    st.write("**Local model**")
    st.code(MODEL, language=None)
    if st.button("Check connection", use_container_width=True):
        try:
            with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as response:
                names = [m["name"] for m in json.load(response).get("models", [])]
            if MODEL in names:
                st.success("Ready — your model is installed.")
            else:
                st.warning(f"Install the model first: ollama pull {MODEL}")
        except (OSError, ValueError, KeyError, TypeError):
            st.error("Open Ollama, then check again.")
    if st.button("New conversation", use_container_width=True):
        st.session_state.messages = [{"role": "system", "content": agent.SYSTEM}]
        st.session_state.turns = []
        st.rerun()
    st.caption("New conversation clears this chat. Saved tasks stay in your notebook.")
    st.divider()
    st.write("**Try asking**")
    st.caption('“Add Review resume with medium priority.”')
    st.caption('“Make that high priority.”')
    st.caption('“What should I work on first?”')
    st.info("I manage tasks only. I cannot browse the web or send reminder notifications.")
    st.caption("One local user. Browser sessions share this task notebook.")

st.title("A little clarity for your day.")
st.write("Tell FocusDesk what needs doing. See each tool action as it happens.")
chat_col, tasks_col = st.columns([1.75, 1], gap="large")

with tasks_col:
    st.subheader("Your notebook")
    notebook = st.empty()


def show_notebook():
    _, result = agent.dispatch({"function": {"name": "list_tasks", "arguments": {"status": "all"}}}, store, {})
    with notebook.container():
        if "error" in result:
            st.error(result["message"])
        elif not result["tasks"]:
            st.info("No tasks yet. Add your first task in the chat.")
        else:
            tasks = result["tasks"]
            st.caption(f"{sum(t['status'] == 'open' for t in tasks)} open · {sum(t['status'] == 'done' for t in tasks)} completed")
            for task in tasks:
                with st.container(border=True):
                    st.text(f"#{task['id']}  {task['title']}")
                    st.caption(f"{task['priority'].upper()} priority · {task['status']}")
        st.caption("Saved locally with SQLite. The notebook refreshes after each request.")


show_notebook()
with chat_col:
    st.subheader("Chat")
    if not st.session_state.turns:
        st.info("Welcome! Try adding a task, then ask me to change its priority.")
    for turn in st.session_state.turns:
        with st.chat_message("user"):
            st.write(turn["question"])
        with st.chat_message("assistant"):
            if turn["events"]:
                with st.expander("Tool activity"):
                    render_events(turn["events"])
            if turn.get("error"):
                st.error(turn["answer"])
            else:
                st.write(turn["answer"])

    question = st.chat_input("Ask about your tasks…", max_chars=2000)
    if question:
        question = question.strip()
        if question:
            turn = {"question": question, "events": [], "answer": "", "error": False}
            st.session_state.turns.append(turn)
            st.session_state.messages.append({"role": "user", "content": question})
            with st.chat_message("user"):
                st.write(question)
            with st.chat_message("assistant"):
                with st.status("Connecting to your local model…", expanded=True) as activity:
                    def on_event(event):
                        if event["kind"] == "model":
                            activity.update(label="Waiting for the local model…", expanded=True)
                        else:
                            turn["events"].append(event)
                            render_events([event])
                            if event["kind"] == "tool_start":
                                activity.update(label="Running a task tool…", expanded=True)
                            elif event["kind"] == "tool_result":
                                show_notebook()

                    try:
                        turn["answer"] = agent.run_turn(
                            st.session_state.messages, MODEL, store,
                            request_chat=agent.chat, on_event=on_event)
                        activity.update(label="Request finished", state="complete", expanded=False)
                    except RuntimeError as exc:
                        turn["error"] = True
                        turn["answer"] = str(exc) + " Any earlier successful changes remain saved. Check your notebook before retrying."
                        activity.update(label="Could not finish this request", state="error")
                if turn["error"]:
                    st.error(turn["answer"])
                else:
                    st.write(turn["answer"])
            show_notebook()

