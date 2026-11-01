"""Tests for the Colour of the Day brief parsing, diary placement and painting retries."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import copilot
from scripts.copilot import (
    COLOUR_SECTION,
    replace_journal_copilot_section,
    split_colour_brief,
    upsert_colour_image,
)

IMG = "![Colour of the Day](../../paintings/2026/01/2026-01-01-colour.png)"


class SplitBriefTest(unittest.TestCase):
    def test_reading_and_prompt(self):
        reading, prompt = split_colour_brief("## Reading\n灰里透一点暖。\n\n## Prompt\nA grey field.\n")
        self.assertEqual(reading, "灰里透一点暖。")
        self.assertEqual(prompt, "A grey field.")

    def test_prompt_only(self):
        self.assertEqual(split_colour_brief("## Prompt\nA grey field."), ("", "A grey field."))

    def test_missing_prompt(self):
        with self.assertRaises(ValueError):
            split_colour_brief("## Reading\nsomething")
        with self.assertRaises(ValueError):
            split_colour_brief("## Prompt\n\n")


class ColourImageTest(unittest.TestCase):
    DIARY = "## 📸 Daily Moment\n> x\n\n## 💬 From Kai\n\n- [[t]]\n\n## What Life Copilot Said\n\nhi\n"

    def test_sits_between_heading_and_reply(self):
        out = upsert_colour_image(self.DIARY, IMG)
        self.assertIn("## What Life Copilot Said\n\n" + IMG + "\n\nhi\n", out)

    def test_repainting_replaces_once(self):
        once = upsert_colour_image(self.DIARY, IMG.replace("01-01", "01-02"))
        twice = upsert_colour_image(once, IMG)
        self.assertEqual(twice.count("![Colour of the Day]"), 1)
        self.assertIn(IMG, twice)

    def test_moves_old_standalone_section(self):
        old = self.DIARY.replace("## 💬 From Kai", f"{COLOUR_SECTION}\n\n{IMG}\n\n## 💬 From Kai")
        out = upsert_colour_image(old, IMG)
        self.assertNotIn(COLOUR_SECTION, out)
        self.assertIn("## 📸 Daily Moment\n> x\n\n## 💬 From Kai", out)
        self.assertEqual(out.count(IMG), 1)

    def test_needs_the_reply_first(self):
        with self.assertRaises(ValueError):
            upsert_colour_image("## 💬 From Kai\n", IMG)


class RewriteKeepsPaintingTest(unittest.TestCase):
    def test_rewritten_reply_keeps_painting(self):
        painted = upsert_colour_image("## What Life Copilot Said\n\nold\n\n## Next\n", IMG)
        out = replace_journal_copilot_section(painted, "new reply")
        self.assertIn(f"## What Life Copilot Said\n\n{IMG}\n\nnew reply\n\n## Next", out)
        self.assertNotIn("old", out)

    def test_unpainted_reply_unchanged(self):
        out = replace_journal_copilot_section("## What Life Copilot Said\n\nold\n", "new")
        self.assertEqual(out, "## What Life Copilot Said\n\nnew\n")


class RateLimitRetryTest(unittest.TestCase):
    """A rate-limited painting is tried exactly once more; other failures are not retried."""

    LIMITED = "FAILED: image generation failed: http 429 Too Many Requests"

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        for name, value in (
            ("CODEX_HOME", self.home),
            ("CODEX_SESSIONS_DIR", self.home / "sessions"),
            ("find_codex_bin", lambda: "codex"),
        ):
            p = patch.object(copilot, name, value)
            p.start()
            self.addCleanup(p.stop)
        sleep = patch.object(copilot.time, "sleep")
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)
        self.calls = []

    def fake_codex(self, *attempts):
        """Stand in for `codex exec`; each attempt is (thread id, Codex's reply, painted?)."""

        def run(cmd, **kwargs):
            thread, reply, painted = attempts[len(self.calls)]
            self.calls.append(thread)
            if painted:
                out = self.home / "generated_images" / thread
                out.mkdir(parents=True)
                (out / "exec-1.png").write_bytes(b"png")
            events = (
                {"type": "thread.started", "thread_id": thread},
                {"type": "item.completed", "item": {"type": "agent_message", "text": reply}},
            )
            return subprocess.CompletedProcess(cmd, 0, stdout="\n".join(map(json.dumps, events)), stderr="")

        return patch.object(copilot.subprocess, "run", side_effect=run)

    def test_rate_limited_then_painted(self):
        with self.fake_codex(("t1", self.LIMITED, False), ("t2", "DONE", True)), redirect_stderr(StringIO()):
            image = copilot.generate_image_with_codex("A grey field.")
        self.assertEqual(image, self.home / "generated_images" / "t2" / "exec-1.png")
        self.assertEqual(self.calls, ["t1", "t2"])
        self.sleep.assert_called_once_with(copilot.PAINT_RETRY_WAIT)

    def test_tried_only_once_more(self):
        with self.fake_codex(("t1", self.LIMITED, False), ("t2", self.LIMITED, False)), redirect_stderr(StringIO()):
            with self.assertRaises(copilot.NoImageError):
                copilot.generate_image_with_codex("A grey field.")
        self.assertEqual(self.calls, ["t1", "t2"])

    def test_other_failures_not_retried(self):
        with self.fake_codex(("t1", "FAILED: image generation failed: content policy", False)):
            with self.assertRaises(copilot.NoImageError) as caught:
                copilot.generate_image_with_codex("A grey field.")
        self.assertIn("content policy", str(caught.exception))
        self.assertEqual(self.calls, ["t1"])
        self.sleep.assert_not_called()

    def test_rate_limit_behind_a_bare_done_is_read_from_the_session_log(self):
        log = self.home / "sessions" / "2026" / "10" / "31" / "rollout-2026-10-31T23-14-48-t1.jsonl"
        log.parent.mkdir(parents=True)
        error = 'Script error:\nimage generation failed: http 429 Too Many Requests: Some("<html>")'
        log.write_text(json.dumps({"payload": {"output": [{"text": error}]}}) + "\n", encoding="utf-8")
        with self.fake_codex(("t1", "DONE", False), ("t2", "DONE", True)), redirect_stderr(StringIO()) as err:
            copilot.generate_image_with_codex("A grey field.")
        self.assertEqual(self.calls, ["t1", "t2"])
        self.assertIn("DONE [image generation failed: http 429 Too Many Requests]", err.getvalue())


if __name__ == "__main__":
    unittest.main()
