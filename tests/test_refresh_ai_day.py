"""Tests for the daytime trace refresh (refresh-ai-day)."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from scripts import copilot

DAY = date(2026, 8, 13)
CODEX_THREAD = "### Codex Thread 11111111-1111-4111-8111-111111111111"
CODEX_ID = "11111111-1111-4111-8111-111111111111"
KAI_SESSION = "### Kai / Telegram Session 22222222-2222-4222-8222-222222222222"


def _ts(hour: int, minute: int) -> str:
    return datetime(2026, 8, 13, hour, minute).astimezone().isoformat()


def _msg(hour: int, minute: int, speaker: str, text: str) -> str:
    return f"[{copilot.format_chat_timestamp(_ts(hour, minute))}] {speaker}: {text}"


def _join(*parts: str) -> str:
    return "\n\n".join(parts) + "\n"


class RefreshAiDayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.traces = self.root / "journal" / "ai-conversations" / "2026" / "08"
        self.journal = self.root / "journal" / "2026" / "08" / "2026-08-13.md"
        self.codex = _join(CODEX_THREAD, _msg(9, 0, "Henry", "早上的问题"), _msg(9, 1, "Codex", "早上的回答"))
        self.kai = _join(KAI_SESSION, _msg(10, 0, "Henry", "路上说的话"), _msg(10, 1, "Kai", "路上的回应"))
        self.openclaw = patch.object(copilot, "export_openclaw_day_transcript", return_value=(self.kai, 1, 2))
        self.patchers = [
            patch.object(copilot, "ROOT", self.root),
            patch.object(copilot, "JOURNAL_DIR", self.root / "journal"),
            patch.object(copilot, "AI_CONVERSATIONS_DIR", self.root / "journal" / "ai-conversations"),
            patch.object(copilot, "export_codex_day_transcript", return_value=self.codex),
            patch.object(copilot, "codex_day_source_records", return_value=[]),
            patch.object(copilot, "export_life_claude_renderer_day_transcript", return_value=("", 0, 0)),
            patch.object(copilot, "export_claude_code_day_transcript", return_value=("", 0, 0)),
            patch.object(copilot, "openclaw_day_source_records", return_value=[]),
            patch.object(copilot, "refresh_web_chats_for_writeback",
                         side_effect=AssertionError("the refresh must never sync web chats")),
        ]
        for patcher in self.patchers:
            patcher.start()
        self.export_openclaw = self.openclaw.start()

    def tearDown(self) -> None:
        self.openclaw.stop()
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def _refresh(self, *argv: str) -> str:
        args = copilot.build_parser().parse_args(["refresh-ai-day", "--date", "2026-08-13", *argv])
        output = io.StringIO()
        with redirect_stdout(output):
            args.func(args)
        return output.getvalue()

    def test_writes_traces_and_timeline_without_a_diary(self):
        output = self._refresh()
        self.assertFalse(self.journal.exists())
        self.assertIn("早上的问题", (self.traces / "2026-08-13-codex-trace.md").read_text(encoding="utf-8"))
        self.assertIn("路上说的话", (self.traces / "2026-08-13-openclaw-trace.md").read_text(encoding="utf-8"))
        self.assertTrue((self.traces / "2026-08-13-timeline.md").exists())
        self.assertIn("refreshed 2026-08-13:", output)
        self.assertIn("2026-08-13-codex-trace.md", output)
        self.assertTrue(output.rstrip().endswith("openclaw: pulled"))

    def test_leaves_an_existing_diary_untouched(self):
        self.journal.parent.mkdir(parents=True)
        diary = "# 2026-08-13\n\nHenry is typing here\n\n## 💬 From Kai\n"
        self.journal.write_text(diary, encoding="utf-8")
        before = self.journal.stat().st_mtime_ns
        self._refresh()
        self.assertEqual(self.journal.read_text(encoding="utf-8"), diary)
        self.assertEqual(self.journal.stat().st_mtime_ns, before)

    def test_second_run_with_nothing_new_writes_nothing(self):
        self._refresh()
        paths = sorted(self.traces.iterdir())
        for path in paths:
            os.utime(path, ns=(1_000_000_000, 1_000_000_000))
        output = self._refresh()
        self.assertEqual(output.strip(), "openclaw: pulled")
        self.assertEqual([path.stat().st_mtime_ns for path in paths], [1_000_000_000] * len(paths))

    def test_new_message_rewrites_only_the_trace_that_changed(self):
        self._refresh()
        kai_trace = self.traces / "2026-08-13-openclaw-trace.md"
        os.utime(kai_trace, ns=(1_000_000_000, 1_000_000_000))
        longer = self.codex + "\n" + _msg(11, 0, "Henry", "新的一句") + "\n"
        with patch.object(copilot, "export_codex_day_transcript", return_value=longer):
            output = self._refresh()
        self.assertIn("新的一句", (self.traces / "2026-08-13-codex-trace.md").read_text(encoding="utf-8"))
        self.assertEqual(kai_trace.stat().st_mtime_ns, 1_000_000_000)
        self.assertIn("2026-08-13-codex-trace.md", output)
        self.assertNotIn("openclaw-trace.md", output)

    def test_no_openclaw_does_not_connect_and_keeps_the_kai_trace(self):
        self._refresh()
        kai_trace = self.traces / "2026-08-13-openclaw-trace.md"
        archived = kai_trace.read_text(encoding="utf-8")
        self.export_openclaw.reset_mock()
        output = self._refresh("--no-openclaw")
        self.export_openclaw.assert_not_called()
        self.assertEqual(kai_trace.read_text(encoding="utf-8"), archived)
        self.assertTrue(output.rstrip().endswith("openclaw: skipped"))

    def test_unreachable_kai_is_quiet_and_keeps_the_kai_trace(self):
        self._refresh()
        kai_trace = self.traces / "2026-08-13-openclaw-trace.md"
        archived = kai_trace.read_text(encoding="utf-8")
        self.export_openclaw.side_effect = copilot.OpenClawImportUnavailable("ssh timed out")
        output = self._refresh()
        self.assertEqual(output.strip(), "openclaw: unavailable")
        self.assertEqual(kai_trace.read_text(encoding="utf-8"), archived)

    def test_day_without_conversations_is_not_an_error(self):
        self.export_openclaw.return_value = ("", 0, 0)
        with patch.object(copilot, "export_codex_day_transcript", return_value=""):
            output = self._refresh()
        self.assertEqual(output.strip(), "openclaw: pulled")
        self.assertFalse(self.traces.exists())

    def test_kept_lost_messages_stay_in_the_trace_without_a_warning_each_run(self):
        self._refresh()
        shorter = _join(CODEX_THREAD, _msg(9, 1, "Codex", "早上的回答"))
        with patch.object(copilot, "export_codex_day_transcript", return_value=shorter):
            first = self._refresh()
            second = self._refresh()
        codex_trace = (self.traces / "2026-08-13-codex-trace.md").read_text(encoding="utf-8")
        self.assertIn("早上的问题", codex_trace)
        self.assertNotIn("WARNING", first + second)

    def test_nightly_writeback_still_requires_and_updates_the_diary(self):
        with self.assertRaises(FileNotFoundError), redirect_stdout(io.StringIO()):
            copilot.writeback_ai_day(DAY)
        self.journal.parent.mkdir(parents=True)
        self.journal.write_text("# 2026-08-13\n\n## 💬 From Kai\n", encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            result = copilot.writeback_ai_day(DAY)
        self.assertIn("2026-08-13-codex-trace", self.journal.read_text(encoding="utf-8"))
        self.assertEqual(result["journal"], str(self.journal))
        self.assertEqual(result["openclaw_status"], "pulled")


if __name__ == "__main__":
    unittest.main()
