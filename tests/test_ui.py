"""Headless UI regression checks. Model replies are scripted, not live LLM tests."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
import task_agent as agent


def tool(name, **args):
    return {"role": "assistant", "tool_calls": [{"function": {"name": name, "arguments": args}}]}


class UITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "test.db"
        self.env = patch.dict(os.environ, {"FOCUSDESK_DB": str(self.db)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.ui = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=60).run()

    def send(self, text, replies):
        with patch.object(agent, "chat", side_effect=replies):
            self.ui.chat_input[0].set_value(text).run()
        self.assertEqual(len(self.ui.exception), 0)

    def test_add_memory_priority_and_reset_preserve_tasks(self):
        self.send("Add Review resume", [tool("add_task", title="Review resume"), {"role": "assistant", "content": "Added #1 Review resume."}])
        self.assertEqual(self.ui.session_state.turns[0]["events"][0]["kind"], "tool_start")
        self.send("Make that high priority", [tool("find_tasks", query="#1"), tool("prioritize_task", query="#1", priority="high"), {"role": "assistant", "content": "Updated #1."}])
        self.assertEqual(len(self.ui.session_state.turns), 2)
        result = agent.TaskStore(self.db).execute("list_tasks", {}, {})
        self.assertEqual(result["tasks"][0]["priority"], "high")
        self.ui.sidebar.button[1].click().run()
        self.assertEqual(len(self.ui.session_state.turns), 0)
        self.assertEqual(len(agent.TaskStore(self.db).execute("list_tasks", {}, {})["tasks"]), 1)

    def test_model_failure_shows_error_and_keeps_saved_action(self):
        self.send("Add Review resume", [tool("add_task", title="Review resume"), RuntimeError("Ollama unavailable")])
        self.assertTrue(self.ui.session_state.turns[0]["error"])
        self.assertIn("remain saved", self.ui.error[0].value)
        self.assertEqual(len(agent.TaskStore(self.db).execute("list_tasks", {}, {})["tasks"]), 1)

    def test_ambiguous_search_asks_without_mutation(self):
        store = agent.TaskStore(self.db)
        for title in ["Study Python", "Finish Python project"]:
            store.execute("add_task", {"title": title}, {})
        self.send("Complete my Python task", [tool("find_tasks", query="Python")])
        self.assertIn("Which task ID", self.ui.session_state.turns[0]["answer"])
        self.assertTrue(all(t["status"] == "open" for t in store.execute("list_tasks", {}, {})["tasks"]))


class EventTests(unittest.TestCase):
    def test_events_bracket_actual_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            store = agent.TaskStore(Path(folder) / "tasks.db")
            events = []
            def observe(event):
                events.append(event["kind"])
                if event["kind"] == "tool_start":
                    self.assertFalse(store.path.exists())
                if event["kind"] == "tool_result":
                    self.assertTrue(store.path.exists())
            replies = iter([tool("add_task", title="Demo"), {"role": "assistant", "content": "Added."}])
            agent.run_turn([], "test", store, lambda *_: next(replies), observe)
            self.assertEqual(events, ["model", "tool_start", "tool_result", "model"])


if __name__ == "__main__":
    unittest.main()
