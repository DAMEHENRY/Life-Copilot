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

    def test_remote_read_reports_missing_file_without_retrying(self):
        missing = type(
            "Result",
            (),
            {
                "returncode": 1,
                "stderr": "cat: /home/henry/new.jsonl: No such file or directory\n",
            },
        )()

        with patch.object(
            copilot.subprocess,
            "run",
            return_value=missing,
        ) as run, patch.object(copilot.time, "sleep"):
            with self.assertRaises(copilot.OpenClawRemoteFileMissing):
                copilot.read_openclaw_remote_text("/home/henry/new.jsonl")

        self.assertEqual(run.call_count, 1)

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

    def test_day_export_uses_supported_direct_index_entries(self):
        index = {
            "agent:main:telegram:direct:owner": {"sessionId": "direct-session"},
            "agent:main:openclaw-weixin:direct:owner": {"sessionId": "weixin-session"},
            "agent:main:telegram:group:@heartbeat": {"sessionId": "heartbeat-session"},
            "agent:main:explicit:test": {"sessionId": "test-session"},
        }
        direct = "\n".join(
            [
                record("user", "day event", "2026-07-26T02:00:00.000Z"),
                record("assistant", "seen", "2026-07-26T02:00:01.000Z"),
            ]
        )
        weixin = "\n".join(
            [
                record("user", "微信消息", "2026-07-26T03:00:00.000Z"),
                record("assistant", "微信收到", "2026-07-26T03:00:01.000Z"),
            ]
        )

        def remote_read(path):
            if path.endswith("sessions.json"):
                return json.dumps(index)
            if path.endswith("direct-session.jsonl"):
                return direct
            if path.endswith("weixin-session.jsonl"):
                return weixin
            raise AssertionError(f"unexpected remote read: {path}")

        with patch.object(copilot, "read_openclaw_remote_text", side_effect=remote_read), \
             patch.object(copilot, "list_openclaw_remote_direct_session_paths", return_value=[]), \
             patch.object(copilot, "timestamp_to_local_date", return_value=date(2026, 7, 26)):
            text, message_count, session_count = copilot.export_openclaw_day_transcript(
                date(2026, 7, 26)
            )

        self.assertEqual(message_count, 4)
        self.assertEqual(session_count, 2)
        self.assertIn("Kai / Telegram Session direct-session", text)
        self.assertIn("Kai / WeChat Session weixin-session", text)
        self.assertNotIn("heartbeat-session", text)
        self.assertNotIn("test-session", text)

    def test_day_export_recovers_retained_direct_session_missing_from_index(self):
        retained_path = (
            f"{copilot.OPENCLAW_SESSIONS_DIR}/"
            "11111111-1111-1111-1111-111111111111.jsonl.reset.2026-07-27T00-00-00Z"
        )
        retained = "\n".join(
            [
                json.dumps(
                    {
                        "type": "message",
                        "timestamp": "2026-07-26T04:00:00.000Z",
                        "message": {
                            "role": "user",
                            "sourceChannel": "telegram",
                            "content": "索引外的凌晨对话",
                        },
                    },
                    ensure_ascii=False,
                ),
                record("assistant", "仍然找回", "2026-07-26T04:00:01.000Z"),
            ]
        )

        def remote_read(path):
            if path.endswith("sessions.json"):
                return "{}"
            if path == retained_path:
                return retained
            raise AssertionError(f"unexpected remote read: {path}")

        with patch.object(copilot, "read_openclaw_remote_text", side_effect=remote_read), \
             patch.object(
                 copilot,
                 "list_openclaw_remote_direct_session_paths",
                 return_value=[retained_path],
             ), \
             patch.object(copilot, "timestamp_to_local_date", return_value=date(2026, 7, 26)):
            text, message_count, session_count = copilot.export_openclaw_day_transcript(
                date(2026, 7, 26)
            )

        self.assertEqual(message_count, 2)
        self.assertEqual(session_count, 1)
        self.assertIn("索引外的凌晨对话", text)
        self.assertIn("Kai / Telegram Session 11111111-1111-1111-1111-111111111111", text)

    def test_day_export_skips_indexed_session_before_its_first_message(self):
        index = {
            "agent:main:telegram:direct:owner": {"sessionId": "fresh-session"},
        }
        retained_path = (
            f"{copilot.OPENCLAW_SESSIONS_DIR}/"
            "22222222-2222-2222-2222-222222222222.jsonl.reset.2026-07-26T14-00-00Z"
        )
        retained = "\n".join(
            [
                json.dumps(
                    {
                        "type": "message",
                        "timestamp": "2026-07-26T04:00:00.000Z",
                        "message": {
                            "role": "user",
                            "sourceChannel": "telegram",
                            "content": "重置前的对话",
                        },
                    },
                    ensure_ascii=False,
                ),
                record("assistant", "收到", "2026-07-26T04:00:01.000Z"),
            ]
        )

        def remote_read(path):
            if path.endswith("sessions.json"):
                return json.dumps(index)
            if path.endswith("fresh-session.jsonl"):
                raise copilot.OpenClawRemoteFileMissing(f"{path} does not exist")
            if path == retained_path:
                return retained
            raise AssertionError(f"unexpected remote read: {path}")

        with patch.object(copilot, "read_openclaw_remote_text", side_effect=remote_read), \
             patch.object(
                 copilot,
                 "list_openclaw_remote_direct_session_paths",
                 return_value=[retained_path],
             ), \
             patch.object(copilot, "timestamp_to_local_date", return_value=date(2026, 7, 26)):
            text, message_count, session_count = copilot.export_openclaw_day_transcript(
                date(2026, 7, 26)
            )

        self.assertEqual(message_count, 2)
        self.assertEqual(session_count, 1)
        self.assertIn("重置前的对话", text)
        self.assertNotIn("fresh-session", text)

    def test_day_export_fails_if_retained_session_disappears(self):
        retained_path = (
            f"{copilot.OPENCLAW_SESSIONS_DIR}/"
            "33333333-3333-3333-3333-333333333333.jsonl.deleted.2026-07-26T14-00-00Z"
        )

        def remote_read(path):
            if path.endswith("sessions.json"):
                return "{}"
            raise copilot.OpenClawRemoteFileMissing(f"{path} does not exist")

        with patch.object(copilot, "read_openclaw_remote_text", side_effect=remote_read), \
             patch.object(
                 copilot,
                 "list_openclaw_remote_direct_session_paths",
                 return_value=[retained_path],
             ):
            with self.assertRaises(copilot.OpenClawRemoteFileMissing):
                copilot.export_openclaw_day_transcript(date(2026, 7, 26))

    def test_wechat_delivery_mirror_is_not_archived_twice(self):
        session = "\n".join(
            [
                record("user", "能收到吗", "2026-07-26T05:00:00.000Z"),
                json.dumps(
                    {
                        "type": "message",
                        "timestamp": "2026-07-26T05:00:01.000Z",
                        "message": {
                            "role": "assistant",
                            "provider": "openclaw",
                            "model": "delivery-mirror",
                            "content": [{"type": "text", "text": "能收到。"}],
                        },
                    },
                    ensure_ascii=False,
                ),
                record("assistant", "能收到。", "2026-07-26T05:00:02.000Z"),
            ]
        )

        with patch.object(copilot, "timestamp_to_local_date", return_value=date(2026, 7, 26)):
            text, count = copilot.export_openclaw_session_transcript(
                session, date(2026, 7, 26)
            )

        self.assertEqual(count, 2)
        self.assertEqual(text.count("Kai: 能收到。"), 1)

    def test_openclaw_prompts_and_undelivered_replies_are_not_dialogue(self):
        def with_runtime(role, content, timestamp, runtime):
            return json.dumps(
                {
                    "type": "message",
                    "timestamp": timestamp,
                    "message": {"role": role, "content": content, "__openclaw": runtime},
                },
                ensure_ascii=False,
            )

        owner = {"senderIsOwner": True, "mirrorOrigin": "codex-app-server"}
        runtime_only = {"mirrorOrigin": "codex-app-server"}
        session = "\n".join(
            [
                with_runtime("user", "记一下今天早上跑了五公里", "2026-08-27T01:00:00.000Z", owner),
                record("assistant", [{"type": "text", "text": "记下了。"}], "2026-08-27T01:00:05.000Z"),
                with_runtime(
                    "user",
                    "Pre-compaction memory flush. If nothing to store, reply with NO_REPLY.",
                    "2026-08-27T09:46:21.603Z",
                    runtime_only,
                ),
                record("assistant", [{"type": "text", "text": "NO_REPLY"}], "2026-08-27T09:47:14.795Z"),
                with_runtime(
                    "user",
                    "[cron:0001 喝水] 提醒 Henry：该喝水了。",
                    "2026-08-27T13:00:01.000Z",
                    runtime_only,
                ),
                record("assistant", [{"type": "text", "text": "该喝水了。"}], "2026-08-27T13:00:05.000Z"),
                record(
                    "user",
                    "<<<BEGIN_OPENCLAW_INTERNAL_CONTEXT>>>\nOpenClaw runtime context (internal):\n"
                    "[Internal task completion event]\n<<<END_OPENCLAW_INTERNAL_CONTEXT>>>",
                    "2026-08-27T14:00:00.000Z",
                ),
                record("assistant", [{"type": "text", "text": "报告写好了。"}], "2026-08-27T14:00:05.000Z"),
            ]
        )

        with patch.object(copilot, "timestamp_to_local_date", return_value=date(2026, 8, 27)):
            text, count = copilot.export_openclaw_session_transcript(
                session, date(2026, 8, 27)
            )

        self.assertIn("Henry: 记一下今天早上跑了五公里", text)
        self.assertIn("Kai: 该喝水了。", text)
        self.assertIn("Kai: 报告写好了。", text)
        self.assertNotIn("memory flush", text)
        self.assertNotIn("cron:", text)
        self.assertNotIn("NO_REPLY", text)
        self.assertNotIn("INTERNAL_CONTEXT", text)
        self.assertEqual(count, 4)

    def test_replies_sent_through_the_message_tool_are_archived_once(self):
        def tool_call(name, arguments, timestamp):
            return record(
                "assistant",
                [{"type": "toolCall", "name": name, "arguments": arguments}],
                timestamp,
            )

        mirror = json.dumps(
            {
                "type": "message",
                "timestamp": "2026-09-17T23:43:56.963Z",
                "message": {
                    "role": "assistant",
                    "provider": "openclaw",
                    "model": "delivery-mirror",
                    "content": [{"type": "text", "text": "好，明早 8 点提醒你。"}],
                },
            },
            ensure_ascii=False,
        )
        session = "\n".join(
            [
                record("user", "明早提醒我带伞", "2026-09-17T23:43:26.208Z"),
                mirror,
                tool_call("cron", {"action": "add"}, "2026-09-17T23:43:56.985Z"),
                tool_call("message", {"action": "send", "message": "好，明早 8 点提醒你。"}, "2026-09-17T23:43:56.989Z"),
                tool_call(
                    "message",
                    {"action": "send", "channel": "telegram", "target": "100000001", "message": "出门记得带伞。\\n\\n下午有雨。"},
                    "2026-09-18T13:00:49.931Z",
                ),
                tool_call(
                    "message",
                    {"action": "send", "channel": "telegram", "target": "someone-else", "message": "not for Henry"},
                    "2026-09-18T13:01:00.000Z",
                ),
            ]
        )

        with patch.object(copilot, "timestamp_to_local_date", return_value=date(2026, 9, 18)):
            messages = copilot.openclaw_session_visible_messages(
                session, date(2026, 9, 18), frozenset({"100000001"})
            )

        self.assertEqual(
            [(role, text) for _, role, text in messages],
            [
                ("user", "明早提醒我带伞"),
                ("assistant", "好，明早 8 点提醒你。"),
                ("assistant", "出门记得带伞。\n\n下午有雨。"),
            ],
        )

    def test_day_export_skips_heartbeat_sub_session(self):
        index = {
            "agent:main:telegram:direct:100000001": {"sessionId": "main-session"},
            "agent:main:telegram:direct:100000001:heartbeat": {"sessionId": "heartbeat-session"},
        }
        files = {
            "sessions.json": json.dumps(index),
            "main-session.jsonl": record("user", "早", "2026-09-07T01:00:00.000Z"),
            "heartbeat-session.jsonl": record("user", "[OpenClaw heartbeat poll]", "2026-09-07T14:27:14.828Z"),
        }

        def fake_read(path, *args, **kwargs):
            return files[path.rsplit("/", 1)[-1]]

        with patch.object(copilot, "read_openclaw_remote_text", side_effect=fake_read), patch.object(
            copilot, "list_openclaw_remote_direct_session_paths", return_value=[]
        ), patch.object(copilot, "timestamp_to_local_date", return_value=date(2026, 9, 7)):
            text, count, sessions = copilot.export_openclaw_day_transcript(date(2026, 9, 7))

        self.assertIn("Henry: 早", text)
        self.assertNotIn("heartbeat poll", text)
        self.assertEqual((count, sessions), (1, 1))

    def test_manual_channel_block_replaces_partial_generated_channel(self):
        generated = (
            "### Kai / Telegram Session remote\n\n"
            "[8/13/26 4:49 AM] Henry: 你在线吗\n\n"
            "### Kai / WeChat Session wechat\n\n"
            "[8/13/26 10:21 PM] Henry: 你好\n"
        )
        existing = (
            "header\n\n"
            "<!-- openclaw-manual-begin channel=telegram source=henry-paste -->\n"
            "### Kai / Telegram (manually supplied by Henry)\n\n"
            "[8/13/26 4:42 AM] Henry: 你在线吗\n\n"
            "[8/13/26 4:51 AM] Kai: 我在线。\n"
            "<!-- openclaw-manual-end -->\n"
        )

        merged = copilot.preserve_manual_openclaw_blocks(generated, existing)

        self.assertNotIn("Telegram Session remote", merged)
        self.assertIn("manually supplied by Henry", merged)
        self.assertIn("Kai: 我在线。", merged)
        self.assertIn("WeChat Session wechat", merged)

    def test_day_export_fails_if_any_direct_session_cannot_be_read(self):
        index = {
            "agent:main:telegram:direct:owner": {"sessionId": "direct-session"},
        }

        def remote_read(path):
            if path.endswith("sessions.json"):
                return json.dumps(index)
            raise copilot.OpenClawImportUnavailable("session read failed")

        with patch.object(copilot, "read_openclaw_remote_text", side_effect=remote_read), \
             patch.object(copilot, "list_openclaw_remote_direct_session_paths", return_value=[]):
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
