import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import scripts.copilot as copilot


def record(role, content, timestamp):
    return json.dumps(
        {
            "type": "message",
            "timestamp": timestamp,
            "message": {"role": role, "content": content},
        },
        ensure_ascii=False,
    )


class TestOpenClawTranscript(unittest.TestCase):
    def test_remote_read_retries_transient_ssh_failure(self):
        failed = type("Result", (), {"returncode": 255, "stderr": "timed out"})()
        succeeded = type("Result", (), {"returncode": 0, "stdout": "contents"})()

        with patch.object(
            copilot.subprocess,
            "run",
            side_effect=[failed, succeeded],
        ) as run, patch.object(copilot.time, "sleep"):
            text = copilot.read_openclaw_remote_text(
                "/home/henry/example.json",
                attempts=2,
            )

        self.assertEqual(text, "contents")
        self.assertEqual(run.call_count, 2)

    def test_remote_read_reports_failure_after_all_attempts(self):
        failed = type("Result", (), {"returncode": 255, "stderr": "timed out"})()

        with patch.object(
            copilot.subprocess,
            "run",
            return_value=failed,
        ) as run, patch.object(copilot.time, "sleep"):
            with self.assertRaisesRegex(
                copilot.OpenClawImportUnavailable,
                "after 3 attempts: timed out",
            ):
                copilot.read_openclaw_remote_text("/home/henry/example.json")

        self.assertEqual(run.call_count, 3)

    def test_visible_messages_only_and_local_date_filter(self):
        session = "\n".join(
            [
                record("user", "你好", "2026-07-26T02:47:32.691Z"),
                record(
                    "assistant",
                    [
                        {"type": "thinking", "thinking": "private reasoning"},
                        {"type": "text", "text": "嗯，刚接上。"},
                        {"type": "toolCall", "name": "read"},
                    ],
                    "2026-07-26T02:47:36.883Z",
                ),
                record(
                    "assistant",
                    [{"type": "text", "text": "嗯，刚接上。"}],
                    "2026-07-26T02:47:37.000Z",
                ),
                record("tool", "tool output", "2026-07-26T02:47:37.000Z"),
                record("user", "tomorrow", "2026-07-26T16:01:00.000Z"),
            ]
        )

        with patch.object(
            copilot,
            "timestamp_to_local_date",
            side_effect=lambda value: (
                date(2026, 7, 27) if value.endswith("16:01:00.000Z") else date(2026, 7, 26)
            ),
        ):
            text, count = copilot.export_openclaw_session_transcript(
                session, date(2026, 7, 26)
            )

        self.assertEqual(count, 2)
        self.assertIn("Henry: 你好", text)
        self.assertIn("Kai: 嗯，刚接上。", text)
        self.assertNotIn("private reasoning", text)
        self.assertNotIn("tool output", text)
        self.assertNotIn("tomorrow", text)

    def test_day_export_uses_only_direct_telegram_index_entries(self):
        index = {
            "agent:main:telegram:direct:owner": {"sessionId": "direct-session"},
            "agent:main:telegram:group:@heartbeat": {"sessionId": "heartbeat-session"},
            "agent:main:explicit:test": {"sessionId": "test-session"},
        }
        direct = "\n".join(
            [
                record("user", "day event", "2026-07-26T02:00:00.000Z"),
                record("assistant", "seen", "2026-07-26T02:00:01.000Z"),
            ]
        )

        def remote_read(path):
            if path.endswith("sessions.json"):
                return json.dumps(index)
            if path.endswith("direct-session.jsonl"):
                return direct
            raise AssertionError(f"unexpected remote read: {path}")

        with patch.object(copilot, "read_openclaw_remote_text", side_effect=remote_read), \
             patch.object(copilot, "timestamp_to_local_date", return_value=date(2026, 7, 26)):
            text, message_count, session_count = copilot.export_openclaw_day_transcript(
                date(2026, 7, 26)
            )

        self.assertEqual(message_count, 2)
        self.assertEqual(session_count, 1)
        self.assertIn("Kai / Telegram Session direct-session", text)
        self.assertNotIn("heartbeat-session", text)
        self.assertNotIn("test-session", text)

    def test_day_export_fails_if_any_direct_session_cannot_be_read(self):
        index = {
            "agent:main:telegram:direct:owner": {"sessionId": "direct-session"},
        }

        def remote_read(path):
            if path.endswith("sessions.json"):
                return json.dumps(index)
            raise copilot.OpenClawImportUnavailable("session read failed")

        with patch.object(copilot, "read_openclaw_remote_text", side_effect=remote_read):
            with self.assertRaisesRegex(
                copilot.OpenClawImportUnavailable,
                "session read failed",
            ):
                copilot.export_openclaw_day_transcript(date(2026, 7, 26))

    def test_writeback_requires_openclaw_by_default_before_any_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal_dir = root / "journal"
            journal_path = journal_dir / "2026" / "07" / "2026-07-26.md"
            journal_path.parent.mkdir(parents=True)
            journal_path.write_text(
                "# 2026-07-26\n\n## 💬 From Kai\n",
                encoding="utf-8",
            )

            with patch.object(copilot, "ROOT", root), \
                 patch.object(copilot, "JOURNAL_DIR", journal_dir), \
                 patch.object(copilot, "AI_CONVERSATIONS_DIR", journal_dir / "ai-conversations"), \
                 patch.object(copilot, "export_codex_day_transcript", return_value="codex"), \
                 patch.object(copilot, "export_life_claude_renderer_day_transcript", return_value=("", 0, 0)), \
                 patch.object(
                     copilot,
                     "export_openclaw_day_transcript",
                     side_effect=copilot.OpenClawImportUnavailable("offline"),
                 ):
                with self.assertRaisesRegex(
                    copilot.OpenClawImportUnavailable,
                    "no partial writeback was performed",
                ):
                    copilot.cmd_writeback_ai_day(
                        SimpleNamespace(
                            date="2026-07-26",
                            allow_missing_openclaw=False,
                        )
                    )

            self.assertFalse((journal_dir / "ai-conversations").exists())

    def test_writeback_can_explicitly_allow_missing_openclaw(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal_dir = root / "journal"
            journal_path = journal_dir / "2026" / "07" / "2026-07-26.md"
            journal_path.parent.mkdir(parents=True)
            journal_path.write_text(
                "# 2026-07-26\n\n## 💬 From Kai\n",
                encoding="utf-8",
            )

            with patch.object(copilot, "ROOT", root), \
                 patch.object(copilot, "JOURNAL_DIR", journal_dir), \
                 patch.object(copilot, "AI_CONVERSATIONS_DIR", journal_dir / "ai-conversations"), \
                 patch.object(copilot, "export_codex_day_transcript", return_value="codex"), \
                 patch.object(copilot, "export_life_claude_renderer_day_transcript", return_value=("", 0, 0)), \
                 patch.object(
                     copilot,
                     "export_openclaw_day_transcript",
                     side_effect=copilot.OpenClawImportUnavailable("offline"),
                 ):
                copilot.cmd_writeback_ai_day(
                    SimpleNamespace(
                        date="2026-07-26",
                        allow_missing_openclaw=True,
                    )
                )

            trace = (
                journal_dir
                / "ai-conversations"
                / "2026"
                / "07"
                / "2026-07-26-codex-trace.md"
            )
            self.assertTrue(trace.exists())


if __name__ == "__main__":
    unittest.main()
