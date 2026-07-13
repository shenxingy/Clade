from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


HOOK_PATH = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "clade"
    / "hooks"
    / "session_context.py"
)
SPEC = importlib.util.spec_from_file_location("clade_session_context", HOOK_PATH)
assert SPEC is not None and SPEC.loader is not None
SESSION_CONTEXT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SESSION_CONTEXT)


class SessionContextHookTests(unittest.TestCase):
    def run_hook(self, event: dict[str, str]) -> dict[str, object]:
        stdin = io.StringIO(json.dumps(event))
        stdout = io.StringIO()
        with patch.object(SESSION_CONTEXT.sys, "stdin", stdin), patch.object(
            SESSION_CONTEXT.sys, "stdout", stdout
        ):
            self.assertEqual(SESSION_CONTEXT.main(), 0)
        return json.loads(stdout.getvalue()) if stdout.getvalue() else {}

    def test_usage_is_visible_outside_git_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            SESSION_CONTEXT, "_usage_message", return_value="project 🐥 -9% (6d)"
        ), patch.object(SESSION_CONTEXT, "_git", return_value=""):
            output = self.run_hook({"cwd": temp_dir})

        self.assertEqual(output, {"systemMessage": "Usage · project 🐥 -9% (6d)"})

    def test_usage_and_repository_context_are_both_emitted(self) -> None:
        def fake_git(_cwd: Path, *args: str) -> str:
            values = {
                ("rev-parse", "--is-inside-work-tree"): "true",
                ("branch", "--show-current"): "main",
                ("log", "-5", "--oneline"): "abc123 test commit",
                ("status", "--short"): "",
            }
            return values.get(args, "")

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            SESSION_CONTEXT, "_usage_message", return_value="project(main) 🐥 -9% (6d)"
        ), patch.object(SESSION_CONTEXT, "_git", side_effect=fake_git):
            output = self.run_hook({"cwd": temp_dir})

        self.assertEqual(
            output["systemMessage"], "Usage · project(main) 🐥 -9% (6d)"
        )
        hook_output = output["hookSpecificOutput"]
        self.assertEqual(hook_output["hookEventName"], "SessionStart")
        self.assertIn("Branch: main", hook_output["additionalContext"])

    def test_usage_failure_does_not_block_repository_context(self) -> None:
        def fake_git(_cwd: Path, *args: str) -> str:
            return "true" if args == ("rev-parse", "--is-inside-work-tree") else ""

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            SESSION_CONTEXT, "_usage_message", return_value=""
        ), patch.object(SESSION_CONTEXT, "_git", side_effect=fake_git):
            output = self.run_hook({"cwd": temp_dir})

        self.assertNotIn("systemMessage", output)
        self.assertIn("hookSpecificOutput", output)


if __name__ == "__main__":
    unittest.main()
