import base64
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
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


def batched(remote_read):
    """Serve the batched reader from the same fake as single-file reads."""

    def read_many(paths, **kwargs):
        texts = {}
        for path in paths:
            try:
                texts[path] = remote_read(path)
            except copilot.OpenClawRemoteFileMissing:
                continue
        return texts

    return read_many


FILE_ONLY_STORE = {"version": 1, "store": False, "index": {}, "transcripts": [], "cold": []}


def zstd_compress(data, content_size=True):
    """Compress a fixture, or return None when this machine has no zstd."""
    try:
        import zstandard
    except ImportError:
        zstandard = None
    if zstandard is not None:
        return zstandard.ZstdCompressor(write_content_size=content_size).compress(data)
    binary = shutil.which("zstd")
    if binary is None:
        return None
    flags = ["-c"] if content_size else ["-c", "--no-content-size"]
    return subprocess.run([binary, *flags], input=data, capture_output=True, check=True).stdout


class TestOpenClawTranscript(unittest.TestCase):
    def setUp(self):
        # These tests describe a host on the file-only layout (OpenClaw <= 2026.7).
        patcher = patch.object(copilot, "read_openclaw_store", return_value=dict(FILE_ONLY_STORE))
        patcher.start()
        self.addCleanup(patcher.stop)

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
             patch.object(copilot, "read_openclaw_remote_texts", side_effect=batched(remote_read)), \
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
             patch.object(copilot, "read_openclaw_remote_texts", side_effect=batched(remote_read)), \
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
             patch.object(copilot, "read_openclaw_remote_texts", side_effect=batched(remote_read)), \
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

    def test_archive_closed_before_the_day_is_not_fetched(self):
        stale = (
            f"{copilot.OPENCLAW_SESSIONS_DIR}/"
            "44444444-4444-4444-4444-444444444444.jsonl.reset.2026-07-20T00-00-00Z"
        )
        fresh = (
            f"{copilot.OPENCLAW_SESSIONS_DIR}/"
            "55555555-5555-5555-5555-555555555555.jsonl.reset.2026-07-26T14-00-00Z"
        )
        session = "\n".join(
            [
                json.dumps(
                    {
                        "type": "message",
                        "timestamp": "2026-07-26T04:00:00.000Z",
                        "message": {
                            "role": "user",
                            "sourceChannel": "telegram",
                            "content": "当天的对话",
                        },
                    },
                    ensure_ascii=False,
                ),
                record("assistant", "收到", "2026-07-26T04:00:01.000Z"),
            ]
        )
        requested = []

        def remote_read(path):
            if path.endswith("sessions.json"):
                return "{}"
            if path == fresh:
                return session
            raise AssertionError(f"unexpected remote read: {path}")

        def read_many(paths, **kwargs):
            requested.extend(paths)
            return batched(remote_read)(paths)

        with patch.object(copilot, "read_openclaw_remote_text", side_effect=remote_read), \
             patch.object(copilot, "read_openclaw_remote_texts", side_effect=read_many), \
             patch.object(
                 copilot,
                 "list_openclaw_remote_direct_session_paths",
                 return_value=[stale, fresh],
             ), \
             patch.object(copilot, "timestamp_to_local_date", return_value=date(2026, 7, 26)):
            text, message_count, _ = copilot.export_openclaw_day_transcript(date(2026, 7, 26))

        self.assertEqual(requested, [fresh])
        self.assertEqual(message_count, 2)
        self.assertIn("当天的对话", text)

    def test_archive_closed_on_the_previous_utc_day_is_still_fetched(self):
        # 2026-07-25T20:00Z is 2026-07-26 04:00 in Henry's timezone.
        name = "66666666-6666-6666-6666-666666666666.jsonl.deleted.2026-07-25T20-00-00Z"
        self.assertFalse(copilot.openclaw_archive_closed_before(name, date(2026, 7, 26)))
        self.assertTrue(copilot.openclaw_archive_closed_before(name, date(2026, 7, 28)))
        # An active transcript carries no closing stamp and is always read.
        self.assertFalse(
            copilot.openclaw_archive_closed_before("live-session.jsonl", date(2026, 7, 26))
        )

    def test_batched_read_returns_one_entry_per_archived_file(self):
        directory = copilot.OPENCLAW_SESSIONS_DIR
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w:gz") as archive:
            for name, body in (("first.jsonl", "一"), ("second.jsonl", "二")):
                data = body.encode("utf-8")
                info = tarfile.TarInfo(name=f"./{name}")
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        succeeded = type("Result", (), {"returncode": 0, "stdout": payload.getvalue()})()

        with patch.object(copilot.subprocess, "run", return_value=succeeded) as run:
            texts = copilot.read_openclaw_remote_texts([
                f"{directory}/first.jsonl",
                f"{directory}/second.jsonl",
            ])

        self.assertEqual(run.call_count, 1)
        self.assertEqual(texts, {
            f"{directory}/first.jsonl": "一",
            f"{directory}/second.jsonl": "二",
        })
        command = run.call_args[0][0]
        self.assertIn("tar", command)
        self.assertIn("ControlMaster=auto", command)
        # Read-only: the batch only asks the host to write an archive to stdout.
        self.assertNotIn("rm", command)

    def test_batched_read_splits_large_requests_into_chunks(self):
        directory = copilot.OPENCLAW_SESSIONS_DIR
        paths = [f"{directory}/session-{index:03d}.jsonl" for index in range(85)]

        def fake_archive(dir_name, names, **kwargs):
            return {f"{dir_name}/{name}": name for name in names}

        with patch.object(copilot, "read_openclaw_remote_archive", side_effect=fake_archive) as run:
            texts = copilot.read_openclaw_remote_texts(paths)

        self.assertEqual(len(texts), 85)
        self.assertEqual(run.call_count, 3)
        self.assertLessEqual(
            max(len(call[0][1]) for call in run.call_args_list),
            copilot.OPENCLAW_REMOTE_BATCH_SIZE,
        )

    def test_batched_read_reports_transport_failure_after_all_attempts(self):
        failed = type("Result", (), {"returncode": 255, "stdout": b"", "stderr": b"timed out"})()

        with patch.object(copilot.subprocess, "run", return_value=failed) as run, \
             patch.object(copilot.time, "sleep"):
            with self.assertRaisesRegex(
                copilot.OpenClawImportUnavailable,
                "after 3 attempts: timed out",
            ):
                copilot.read_openclaw_remote_texts([
                    f"{copilot.OPENCLAW_SESSIONS_DIR}/first.jsonl",
                ])

        self.assertEqual(run.call_count, 3)

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
             patch.object(copilot, "read_openclaw_remote_texts", side_effect=batched(remote_read)), \
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
            copilot, "read_openclaw_remote_texts", side_effect=batched(fake_read)
        ), patch.object(
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
             patch.object(copilot, "read_openclaw_remote_texts", side_effect=batched(remote_read)), \
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


DAY = date(2026, 10, 5)
SESSION = "99999999-9999-4999-8999-999999999999"
OWNER_KEY = "agent:main:telegram:direct:100000001"


def local_time(day, hour, minute=0):
    return datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute).astimezone()


def stamp(moment):
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def millis(moment):
    return int(moment.timestamp() * 1000)


def owner_record(text, moment, channel="telegram", media=None, owner=True):
    runtime = {"senderIsOwner": owner}
    if media is not None:
        runtime["media"] = media
    return json.dumps(
        {
            "type": "message",
            "timestamp": stamp(moment),
            "message": {
                "role": "user",
                "sourceChannel": channel,
                "content": text,
                "__openclaw": runtime,
            },
        },
        ensure_ascii=False,
    )


def kai_record(text, moment):
    return record("assistant", [{"type": "text", "text": text}], stamp(moment))


def sessions_json_is_gone(path):
    raise copilot.OpenClawRemoteFileMissing(f"{path} does not exist")


STAGING = "/home/user/.openclaw/workspace/media/inbound/openclaw-staged-00000000-0000-4000-8000-000000000001"


def staged(name, content_type="image/jpeg", kind="image", **extra):
    """A file the owner sent, as OpenClaw 2026.9 lists it on the message."""
    path = f"{STAGING}/{name}"
    return {
        "path": path, "url": path, "contentType": content_type, "kind": kind,
        "workspaceDir": "/home/user/.openclaw/workspace", **extra,
    }


class TestOpenClawAttachments(unittest.TestCase):
    """Files sent to Kai are listed beside the message text, never inside it."""

    def messages(self, *records):
        return [
            (role, text)
            for _, role, text in copilot.openclaw_session_visible_messages("\n".join(records), DAY)
        ]

    def test_attached_images_follow_the_text_as_placeholders(self):
        session = "\n".join([
            owner_record(
                "看一下这两张图",
                local_time(DAY, 11, 30),
                media=[staged("input-aaaa.jpg"), staged("input-bbbb.jpg")],
            ),
            kai_record("看到了。", local_time(DAY, 11, 31)),
        ])

        text, count = copilot.export_openclaw_session_transcript(session, DAY)

        self.assertEqual(count, 2)
        self.assertEqual(
            text,
            f"[{copilot.format_chat_timestamp(stamp(local_time(DAY, 11, 30)))}] Henry: 看一下这两张图\n\n"
            "[Image: input-aaaa.jpg]\n\n"
            "[Image: input-bbbb.jpg]\n\n"
            f"[{copilot.format_chat_timestamp(stamp(local_time(DAY, 11, 31)))}] Kai: 看到了。\n",
        )
        self.assertNotIn(STAGING, text)

    def test_message_with_only_images_is_still_archived(self):
        messages = self.messages(
            owner_record("", local_time(DAY, 9), media=[staged("input-aaaa.jpg")]),
            owner_record("", local_time(DAY, 9, 1), media=[staged("input-bbbb.jpg"), staged("input-cccc.jpg")]),
            owner_record("", local_time(DAY, 9, 2)),
        )

        self.assertEqual(messages, [
            ("user", "[Image: input-aaaa.jpg]"),
            ("user", "[Image: input-bbbb.jpg]\n\n[Image: input-cccc.jpg]"),
        ])

    def test_entries_without_a_kind_are_told_apart_by_content_type(self):
        # OpenClaw 2026.7 and earlier kept only the path and the content type.
        older = [
            {"path": f"{STAGING}/aaaa.jpg", "contentType": "image/jpeg"},
            {"path": f"{STAGING}/bbbb.ogg", "contentType": "audio/ogg"},
        ]

        messages = self.messages(owner_record("两个文件", local_time(DAY, 9), media=older))

        self.assertEqual(messages, [("user", "两个文件\n\n[Image: aaaa.jpg]\n\n[Attachment: bbbb.ogg]")])

    def test_other_files_become_attachment_placeholders(self):
        media = [
            staged("input-dddd.pdf", "application/pdf", "document", fileName="notes [final].pdf"),
            staged("input-eeee.mp4", "video/mp4", "video"),
            {"kind": "audio"},
            {"kind": "image"},
            staged("input-ffff.webp", "image/webp", "sticker"),
            {},
            "not an entry",
        ]

        messages = self.messages(owner_record("", local_time(DAY, 9), media=media))

        self.assertEqual(messages, [(
            "user",
            "[Attachment: notes [final .pdf]\n\n"
            "[Attachment: input-eeee.mp4]\n\n"
            "[Attachment: untitled]\n\n"
            "[Image]\n\n"
            "[Image: input-ffff.webp]",
        )])
        for line in messages[0][1].split("\n\n"):
            # The rewrite guard and the timeline skip these lines by this pattern.
            self.assertTrue(copilot.TRACE_ANNOTATION_RE.fullmatch(line), line)

    def test_only_the_owners_attachments_are_archived(self):
        messages = self.messages(
            owner_record("", local_time(DAY, 9), media=[staged("input-aaaa.jpg")], owner=False),
            owner_record("这张是我发的", local_time(DAY, 9, 1), media=[staged("input-bbbb.jpg")]),
        )

        self.assertEqual(messages, [("user", "这张是我发的\n\n[Image: input-bbbb.jpg]")])


class TestOpenClawStoreExport(unittest.TestCase):
    """Day export on a host whose sessions live in the agent database."""

    def export(self, store, day=DAY):
        with patch.object(copilot, "read_openclaw_store", return_value=store), \
             patch.object(copilot, "read_openclaw_remote_text", side_effect=sessions_json_is_gone), \
             patch.object(copilot, "read_openclaw_remote_texts", return_value={}), \
             patch.object(copilot, "list_openclaw_remote_direct_session_paths", return_value=[]):
            retained = []
            return (*copilot.export_openclaw_day_transcript(day, retained=retained), retained)

    def test_day_export_reads_the_store_when_sessions_json_is_gone(self):
        store = {
            "version": 1,
            "store": True,
            "index": {OWNER_KEY: SESSION},
            "cold": [],
            "transcripts": [
                {
                    "origin": "store",
                    "session_id": SESSION,
                    "channel": "telegram",
                    "name": OWNER_KEY,
                    "rows": [
                        ["j", owner_record("下午到家了", local_time(DAY, 19, 34))],
                        ["j", kai_record("到了就好。", local_time(DAY, 19, 35))],
                        ["j", owner_record("明天的话", local_time(DAY + timedelta(days=1), 9))],
                    ],
                },
            ],
        }

        text, message_count, session_count, retained = self.export(store)

        self.assertEqual((message_count, session_count), (2, 1))
        self.assertIn(f"### Kai / Telegram Session {SESSION}", text)
        self.assertIn("Henry: 下午到家了", text)
        self.assertIn("Kai: 到了就好。", text)
        self.assertNotIn("明天的话", text)
        self.assertEqual([session_id for session_id, _ in retained], [SESSION])

    def test_session_held_by_store_and_imported_file_is_archived_once(self):
        rows = [
            ["j", owner_record("你好", local_time(DAY, 19, 34))],
            ["j", kai_record("你好，Henry。", local_time(DAY, 19, 34))],
        ]
        store = {
            "version": 1,
            "store": True,
            "index": {OWNER_KEY: SESSION},
            "cold": [],
            "transcripts": [
                {"origin": "store", "session_id": SESSION, "channel": "telegram", "rows": rows},
                {"origin": "imported", "session_id": SESSION, "channel": "telegram", "rows": rows},
            ],
        }

        text, message_count, session_count, _ = self.export(store)

        self.assertEqual((message_count, session_count), (2, 1))
        self.assertEqual(text.count("Henry: 你好"), 1)

    def test_sends_to_the_owner_named_only_in_the_store_index_are_kept(self):
        send = record(
            "assistant",
            [{
                "type": "toolCall",
                "name": "message",
                "arguments": {"action": "send", "target": "100000001", "message": "到家了吗"},
            }],
            stamp(local_time(DAY, 20)),
        )
        store = {
            "version": 1,
            "store": True,
            "index": {OWNER_KEY: SESSION},
            "cold": [],
            "transcripts": [
                {"origin": "store", "session_id": SESSION, "channel": "telegram", "rows": [["j", send]]},
            ],
        }

        text, message_count, _, _ = self.export(store)

        self.assertEqual(message_count, 1)
        self.assertIn("Kai: 到家了吗", text)

    def test_archive_without_a_known_channel_is_classified_by_its_content(self):
        direct = "\n".join([
            owner_record("重置前说的话", local_time(DAY, 10), channel="openclaw-weixin"),
            kai_record("收到。", local_time(DAY, 10, 1)),
        ])
        cron = kai_record("索引任务完成", local_time(DAY, 7))
        store = {
            "version": 1,
            "store": True,
            "index": {},
            "cold": [],
            "transcripts": [
                {
                    "origin": "store-archive",
                    "session_id": "11111111-1111-1111-1111-111111111111",
                    "channel": None,
                    "encoding": "identity",
                    "blob": base64.b64encode(direct.encode("utf-8")).decode("ascii"),
                },
                {
                    "origin": "store-archive",
                    "session_id": "22222222-2222-2222-2222-222222222222",
                    "channel": None,
                    "encoding": "identity",
                    "blob": base64.b64encode(cron.encode("utf-8")).decode("ascii"),
                },
            ],
        }

        text, message_count, session_count, _ = self.export(store)

        self.assertEqual((message_count, session_count), (2, 1))
        self.assertIn("### Kai / WeChat Session 11111111-1111-1111-1111-111111111111", text)
        self.assertNotIn("索引任务完成", text)

    def test_compressed_rows_and_archives_are_decoded(self):
        long_reply = kai_record("想听。" + "这一段路你慢慢讲。" * 300, local_time(DAY, 19, 38))
        archived = "\n".join([
            owner_record("重置前的一句", local_time(DAY, 9)),
            kai_record("记下了。", local_time(DAY, 9, 1)),
        ])
        row = zstd_compress(long_reply.encode("utf-8"))
        # Node writes archives as a stream, so the frame carries no content size.
        blob = zstd_compress(archived.encode("utf-8"), content_size=False)
        if row is None or blob is None:
            self.skipTest("no zstd compressor on this machine")
        store = {
            "version": 1,
            "store": True,
            "index": {OWNER_KEY: SESSION},
            "cold": [],
            "transcripts": [
                {
                    "origin": "store",
                    "session_id": SESSION,
                    "channel": "telegram",
                    "rows": [
                        ["j", owner_record("路上的事你想听吗", local_time(DAY, 19, 36))],
                        ["z", base64.b64encode(row).decode("ascii")],
                    ],
                },
                {
                    "origin": "archive-file",
                    "session_id": "33333333-3333-3333-3333-333333333333",
                    "channel": None,
                    "encoding": "zstd",
                    "blob": base64.b64encode(blob).decode("ascii"),
                },
            ],
        }

        text, message_count, session_count, _ = self.export(store)

        self.assertEqual((message_count, session_count), (4, 2))
        self.assertIn("这一段路你慢慢讲。" * 300, text)
        self.assertIn("Henry: 重置前的一句", text)

    def test_day_trace_lists_what_was_attached_to_each_message(self):
        store = {
            "version": 1,
            "store": True,
            "index": {OWNER_KEY: SESSION},
            "cold": [],
            "transcripts": [
                {
                    "origin": "store",
                    "session_id": SESSION,
                    "channel": "telegram",
                    "rows": [
                        ["j", owner_record("帮我记一下", local_time(DAY, 11, 30), media=[staged("input-aaaa.jpg")])],
                        ["j", kai_record("记下了。", local_time(DAY, 11, 31))],
                        ["j", owner_record("", local_time(DAY, 11, 32), media=[staged("input-bbbb.jpg")])],
                    ],
                },
            ],
        }

        text, message_count, session_count, _ = self.export(store)

        self.assertEqual((message_count, session_count), (3, 1))
        self.assertIn("Henry: 帮我记一下\n\n[Image: input-aaaa.jpg]\n\n", text)
        self.assertTrue(text.endswith("Henry: [Image: input-bbbb.jpg]\n"), text)

    def test_corrupt_compressed_row_stops_the_import(self):
        store = {
            "version": 1,
            "store": True,
            "index": {OWNER_KEY: SESSION},
            "cold": [],
            "transcripts": [
                {
                    "origin": "store",
                    "session_id": SESSION,
                    "channel": "telegram",
                    "rows": [["z", base64.b64encode(b"not a zstd frame").decode("ascii")]],
                },
            ],
        }

        with self.assertRaises(copilot.OpenClawImportUnavailable):
            self.export(store)

    def test_cold_archived_direct_chat_stops_the_import(self):
        store = {
            "version": 1,
            "store": True,
            "index": {OWNER_KEY: SESSION},
            "transcripts": [],
            "cold": [{"session_id": SESSION, "name": f"{SESSION}.cold", "direct": True}],
        }

        with self.assertRaisesRegex(copilot.OpenClawImportUnavailable, "cold archive"):
            self.export(store)

    def test_missing_index_still_fails_on_a_file_only_host(self):
        with self.assertRaises(copilot.OpenClawRemoteFileMissing):
            self.export(dict(FILE_ONLY_STORE))


class TestOpenClawStoreReader(unittest.TestCase):
    """Run the host-side reader here, against a database built for the test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.db = root / "agent" / "openclaw-agent.sqlite"
        self.sessions = root / "sessions"
        self.imported = root / "session-sqlite-import-archive"
        for directory in (self.db.parent, self.sessions, self.imported):
            directory.mkdir(parents=True)
        for name, value in (
            ("OPENCLAW_AGENT_DB", str(self.db)),
            ("OPENCLAW_SESSIONS_DIR", str(self.sessions)),
            ("OPENCLAW_IMPORT_ARCHIVE_DIR", str(self.imported)),
            # Stand in for ssh + wsl.exe: run the same script with this Python.
            ("openclaw_ssh_command", lambda *args: [sys.executable, *args[1:]]),
        ):
            patcher = patch.object(copilot, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def build_database(self):
        con = sqlite3.connect(self.db)
        con.executescript(
            """
            create table session_nodes (session_key text primary key, current_session_id text not null);
            create table session_windows (
                session_id text primary key, session_key text not null,
                updated_at integer, transcript_updated_at integer);
            create table transcript_events (
                session_id text not null, seq integer not null, event_json text,
                created_at integer not null, event_zstd blob, navigation_json text,
                primary key (session_id, seq));
            create table session_transcript_archives (
                session_id text, session_key text, encoding text, archive_blob blob,
                archive_name text, created_at integer);
            create table session_transcript_cold_archives (session_id text primary key, archive_name text);
            """
        )
        return con

    def add_session(self, con, session_id, key, events, updated):
        con.execute("insert or replace into session_nodes values (?, ?)", (key, session_id))
        con.execute(
            "insert into session_windows values (?, ?, ?, ?)",
            (session_id, key, millis(updated), millis(updated)),
        )
        for seq, (moment, event_json, event_zstd, navigation) in enumerate(events):
            con.execute(
                "insert into transcript_events values (?, ?, ?, ?, ?, ?)",
                (session_id, seq, event_json, millis(moment), event_zstd, navigation),
            )

    def test_host_without_the_database_is_reported_as_file_only(self):
        store = copilot.read_openclaw_store(DAY)

        self.assertFalse(store["store"])
        self.assertEqual(store["transcripts"], [])

    def test_reader_returns_the_days_direct_chats_and_nothing_else(self):
        noon = local_time(DAY, 12)
        last_week = local_time(DAY - timedelta(days=7), 12)
        tool_result = json.dumps({
            "type": "message",
            "timestamp": stamp(noon),
            "message": {"role": "toolResult", "content": "tool output"},
        })
        compressed_reply = json.dumps({"navigation": {"type": "message", "message": {"role": "assistant"}}})
        compressed_tool = json.dumps({"navigation": {"type": "message", "message": {"role": "toolResult"}}})
        con = self.build_database()
        self.add_session(con, SESSION, OWNER_KEY, [
            (last_week, owner_record("上周的话", last_week), None, None),
            (noon, json.dumps({"type": "session", "timestamp": stamp(noon)}), None, None),
            (noon, owner_record("中午好", noon), None, None),
            (noon, tool_result, None, None),
            (noon, None, b"reply-frame", compressed_reply),
            (noon, None, b"tool-frame", compressed_tool),
        ], updated=noon)
        self.add_session(con, "heartbeat-session", OWNER_KEY + ":heartbeat", [
            (noon, owner_record("[OpenClaw heartbeat poll]", noon), None, None),
        ], updated=noon)
        self.add_session(con, "cron-session", "agent:main:cron:0001", [
            (noon, kai_record("索引任务完成", noon), None, None),
        ], updated=noon)
        self.add_session(con, "recovered-session", "agent:main:recovered:0002", [
            (noon, owner_record("索引丢了的微信对话", noon, channel="openclaw-weixin"), None, None),
        ], updated=noon)
        self.add_session(con, "stale-session", "agent:main:telegram:direct:200000002", [
            (last_week, owner_record("早就结束的会话", last_week), None, None),
        ], updated=last_week)
        con.execute(
            "insert into session_transcript_archives values (?, ?, ?, ?, ?, ?)",
            ("reset-session", OWNER_KEY, "zstd", b"archive-frame", "reset-session.jsonl.reset.x.zst", millis(noon)),
        )
        con.execute(
            "insert into session_transcript_archives values (?, ?, ?, ?, ?, ?)",
            ("old-reset", OWNER_KEY, "zstd", b"old-frame", "old-reset.jsonl.reset.y.zst", millis(last_week)),
        )
        con.execute("insert into session_transcript_cold_archives values (?, ?)", (SESSION, "cold-name"))
        con.commit()
        con.close()

        store = copilot.read_openclaw_store(DAY)

        self.assertTrue(store["store"])
        self.assertEqual(store["index"][OWNER_KEY], SESSION)
        by_session = {entry["session_id"]: entry for entry in store["transcripts"]}
        self.assertEqual(
            sorted(by_session),
            sorted(["recovered-session", "reset-session", SESSION]),
        )
        main = by_session[SESSION]
        self.assertEqual((main["origin"], main["channel"]), ("store", "telegram"))
        self.assertEqual([kind for kind, _ in main["rows"]], ["j", "z"])
        self.assertIn("中午好", main["rows"][0][1])
        self.assertEqual(base64.b64decode(main["rows"][1][1]), b"reply-frame")
        self.assertEqual(by_session["recovered-session"]["channel"], "openclaw-weixin")
        archive = by_session["reset-session"]
        self.assertEqual((archive["origin"], archive["encoding"]), ("store-archive", "zstd"))
        self.assertEqual(base64.b64decode(archive["blob"]), b"archive-frame")
        self.assertEqual(store["cold"], [{"session_id": SESSION, "name": "cold-name", "direct": True}])

    def test_reader_finds_imported_and_compressed_files(self):
        noon = local_time(DAY, 12)
        direct = "\n".join([owner_record("迁移前的对话", noon), kai_record("在。", noon)])
        imported_name = f"agent_main_telegram_direct_100000001.{SESSION}.jsonl.imported-1790000000640"
        (self.imported / imported_name).write_text(direct, encoding="utf-8")
        cron_id = "44444444-4444-4444-4444-444444444444"
        (self.imported / f"archive-tier.{cron_id}.jsonl.imported-1790000000650").write_text(
            kai_record("索引任务完成", noon), encoding="utf-8"
        )
        # Trajectories and macOS resource forks share the directory.
        (self.imported / f"agent_main_x.{SESSION}.trajectory.jsonl.imported-1790000000641").write_text(
            direct, encoding="utf-8"
        )
        (self.imported / f"archive-tier.._{SESSION}.jsonl.imported-1790000000651").write_text(
            direct, encoding="utf-8"
        )
        old_id = "55555555-5555-5555-5555-555555555555"
        old = self.imported / f"archive-tier.{old_id}.jsonl.imported-1790000000652"
        old.write_text(direct, encoding="utf-8")
        week_ago = (local_time(DAY, 12) - timedelta(days=7)).timestamp()
        os.utime(old, (week_ago, week_ago))

        fresh_id = "66666666-6666-6666-6666-666666666666"
        fresh = f"{fresh_id}.jsonl.reset.{DAY.isoformat()}T11-32-10.961Z.0123456789abcdef0123456789abcdef.zst"
        (self.sessions / fresh).write_bytes(b"compressed-archive")
        stale_id = "77777777-7777-7777-7777-777777777777"
        (self.sessions / f"{stale_id}.jsonl.reset.2026-09-01T00-00-00.000Z.zst").write_bytes(b"stale")
        (self.sessions / f"{stale_id}.jsonl.reset.{DAY.isoformat()}T00-00-00.000Z").write_text(direct, encoding="utf-8")

        store = copilot.read_openclaw_store(DAY)

        self.assertFalse(store["store"])
        by_name = {entry["name"]: entry for entry in store["transcripts"]}
        self.assertEqual(sorted(by_name), sorted([imported_name, fresh]))
        self.assertEqual(
            (by_name[imported_name]["origin"], by_name[imported_name]["session_id"], by_name[imported_name]["channel"]),
            ("imported", SESSION, "telegram"),
        )
        self.assertEqual(len(by_name[imported_name]["rows"]), 2)
        self.assertEqual(
            (by_name[fresh]["origin"], by_name[fresh]["session_id"], by_name[fresh]["encoding"]),
            ("archive-file", fresh_id, "zstd"),
        )
        self.assertEqual(base64.b64decode(by_name[fresh]["blob"]), b"compressed-archive")

    def test_reader_output_feeds_the_day_export(self):
        con = self.build_database()
        self.add_session(con, SESSION, OWNER_KEY, [
            (local_time(DAY, 19, 34), owner_record("你好", local_time(DAY, 19, 34)), None, None),
            (local_time(DAY, 19, 35), kai_record("你好，Henry。", local_time(DAY, 19, 35)), None, None),
        ], updated=local_time(DAY, 19, 35))
        con.commit()
        con.close()

        with patch.object(copilot, "read_openclaw_remote_text", side_effect=sessions_json_is_gone), \
             patch.object(copilot, "read_openclaw_remote_texts", return_value={}), \
             patch.object(copilot, "list_openclaw_remote_direct_session_paths", return_value=[]):
            text, message_count, session_count = copilot.export_openclaw_day_transcript(DAY)

        self.assertEqual((message_count, session_count), (2, 1))
        self.assertIn("Henry: 你好", text)
        self.assertIn("Kai: 你好，Henry。", text)

    def test_compressed_event_with_images_reaches_the_day_export(self):
        # The sender, transport and media facts push such an event past the
        # size OpenClaw compresses at, so the host cannot look inside it.
        sent = local_time(DAY, 11, 30)
        event = owner_record("帮我记一下", sent, media=[staged("input-aaaa.jpg"), staged("input-bbbb.jpg")])
        frame = zstd_compress(event.encode("utf-8"))
        if frame is None:
            self.skipTest("no zstd compressor on this machine")
        navigation = json.dumps({"navigation": {"type": "message", "message": {"role": "user"}}})
        con = self.build_database()
        self.add_session(con, SESSION, OWNER_KEY, [(sent, None, frame, navigation)], updated=sent)
        con.commit()
        con.close()

        with patch.object(copilot, "read_openclaw_remote_text", side_effect=sessions_json_is_gone), \
             patch.object(copilot, "read_openclaw_remote_texts", return_value={}), \
             patch.object(copilot, "list_openclaw_remote_direct_session_paths", return_value=[]):
            text, message_count, _ = copilot.export_openclaw_day_transcript(DAY)

        self.assertEqual(message_count, 1)
        self.assertIn("Henry: 帮我记一下\n\n[Image: input-aaaa.jpg]\n\n[Image: input-bbbb.jpg]\n", text)

    def test_reader_failure_is_reported_after_all_attempts(self):
        failed = type("Result", (), {"returncode": 1, "stdout": b"", "stderr": b"Traceback\ndatabase is locked\n"})()

        with patch.object(copilot.subprocess, "run", return_value=failed) as run, \
             patch.object(copilot.time, "sleep"):
            with self.assertRaisesRegex(
                copilot.OpenClawImportUnavailable,
                "session store .* after 3 attempts: database is locked",
            ):
                copilot.read_openclaw_store(DAY)

        self.assertEqual(run.call_count, 3)


if __name__ == "__main__":
    unittest.main()
