import json
import unittest
from datetime import date
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


if __name__ == "__main__":
    unittest.main()
