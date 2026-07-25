"""Contract tests for the project-local bedtime hooks."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = ROOT / ".codex" / "hooks" / "life_copilot_bedtime.py"
CONFIG_PATH = ROOT / ".codex" / "hooks.json"

SPEC = importlib.util.spec_from_file_location("life_copilot_bedtime_hook", HOOK_PATH)
assert SPEC and SPEC.loader
hook = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hook)


class TestBedtimeHookConfig(unittest.TestCase):
    def test_config_registers_user_prompt_and_stop(self):
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            set(config["hooks"]),
            {"UserPromptSubmit", "Stop"},
        )
        for event in ("UserPromptSubmit", "Stop"):
            command = config["hooks"][event][0]["hooks"][0]["command"]
            self.assertIn("git rev-parse --show-toplevel", command)
            self.assertIn("life_copilot_bedtime.py", command)


class TestBedtimeHookFlow(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.marker = self.root / "marker.json"
        self.marker_patch = patch.object(
            hook,
            "marker_path",
            return_value=self.marker,
        )
        self.marker_patch.start()

    def tearDown(self) -> None:
        self.marker_patch.stop()
        self.temp.cleanup()

    def test_direct_request_creates_marker_and_adds_context(self):
        payload = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "session-1",
            "turn_id": "turn-1",
            "prompt": "请用一句有趣且出乎意料的话给我晚安",
            "model": "gpt-test",
        }
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            hook.user_prompt_submit(payload)
        output = json.loads(stdout.getvalue())
        self.assertTrue(self.marker.exists())
        self.assertEqual(
            output["hookSpecificOutput"]["hookEventName"],
            "UserPromptSubmit",
        )
        self.assertIn(
            "恰好一句",
            output["hookSpecificOutput"]["additionalContext"],
        )

    def test_meta_discussion_is_noop(self):
        payload = {
            "session_id": "session-1",
            "turn_id": "turn-1",
            "prompt": "我们讨论晚安功能的触发条件",
        }
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            hook.user_prompt_submit(payload)
        self.assertEqual(json.loads(stdout.getvalue()), {})
        self.assertFalse(self.marker.exists())

    def test_stop_finalizes_and_cleans_marker(self):
        self.marker.write_text(json.dumps({
            "session_id": "session-1",
            "turn_id": "turn-1",
            "date": "2026-07-25",
            "prompt": "跟我说晚安吧",
        }), encoding="utf-8")
        completed = SimpleNamespace(returncode=0, stdout="{}", stderr="")
        stdout = io.StringIO()
        with patch.object(hook.subprocess, "run", return_value=completed) as run:
            with contextlib.redirect_stdout(stdout):
                hook.stop({
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "last_assistant_message": "把今天折进月光里，晚安。",
                })
        self.assertEqual(json.loads(stdout.getvalue()), {})
        self.assertFalse(self.marker.exists())
        command = run.call_args.args[0]
        self.assertIn("finalize-ai-day", command)

    def test_stop_failure_is_visible_but_does_not_block_reply(self):
        self.marker.write_text(json.dumps({
            "session_id": "session-1",
            "turn_id": "turn-1",
            "date": "2026-07-25",
            "prompt": "跟我说晚安吧",
        }), encoding="utf-8")
        completed = SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="simulated archive failure",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.object(hook.subprocess, "run", return_value=completed):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                hook.stop({
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "last_assistant_message": "晚安。",
                })
        self.assertEqual(json.loads(stdout.getvalue()), {})
        self.assertIn("simulated archive failure", stderr.getvalue())
        self.assertTrue(self.marker.exists())


if __name__ == "__main__":
    unittest.main()
