"""Tests for Claude / ChatGPT web chat archiving (host, sync, and day traces)."""

from __future__ import annotations

import io
import json
import os
import select
import struct
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import copilot

HOST_SCRIPT = copilot.ROOT / "tools" / "web-chat-archiver" / "host" / "web_chat_host.py"

MINIMAL_DIARY = textwrap.dedent("""\
    #diary
    # 📅 2026-09-12
    ## 💭 Thoughts & Reflections

    手写内容。

    ## 💬 From Kai

    ## What Life Copilot Said
""")


def _local(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, minute).astimezone()


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def claude_conversation() -> dict:
    root = "00000000-0000-4000-8000-000000000000"
    return {
        "uuid": "c-1",
        "name": "午餐后过敏",
        "current_leaf_message_uuid": "m4",
        "chat_messages": [
            {
                "uuid": "m1", "sender": "human", "parent_message_uuid": root,
                "created_at": _iso(_local(12, 13)),
                "content": [{"type": "text", "text": "脸肿了"}],
                "files": [{"file_kind": "image", "file_name": "face.jpg"}],
                "attachments": [],
            },
            {
                "uuid": "m2-old", "sender": "assistant", "parent_message_uuid": "m1",
                "created_at": _iso(_local(12, 13, 1)),
                "content": [{"type": "text", "text": "OLD BRANCH"}],
            },
            {
                "uuid": "m2", "sender": "assistant", "parent_message_uuid": "m1",
                "created_at": _iso(_local(12, 13, 2)),
                "content": [
                    {"type": "thinking", "thinking": "SECRET THOUGHT"},
                    {"type": "tool_use", "name": "web_search", "input": {}},
                    {"type": "tool_result", "content": [{"type": "text", "text": "TOOL OUTPUT"}]},
                    {"type": "text", "text": "可能是过敏"},
                ],
            },
            {
                "uuid": "m3", "sender": "human", "parent_message_uuid": "m2",
                "created_at": _iso(_local(12, 23, 50)),
                "content": [{"type": "text", "text": "要去医院吗"}],
            },
            {
                "uuid": "m4", "sender": "assistant", "parent_message_uuid": "m3",
                "created_at": _iso(_local(13, 0, 10)),
                "content": [{"type": "text", "text": "先观察"}],
            },
        ],
    }


def _node(node_id, parent, role=None, content_type="text", parts=None, recipient="all", metadata=None, at=None):
    message = None
    if role:
        message = {
            "id": node_id,
            "author": {"role": role},
            "content": {"content_type": content_type, "parts": parts or []},
            "recipient": recipient,
            "metadata": metadata or {},
            "create_time": at.timestamp() if at else None,
        }
    return {"id": node_id, "parent": parent, "children": [], "message": message}


def chatgpt_conversation() -> dict:
    nodes = [
        _node("root", None),
        _node("sys", "root", "system", parts=[""], metadata={"is_visually_hidden_from_conversation": True}),
        _node("ctx", "sys", "user", content_type="user_editable_context", at=_local(12, 9)),
        _node("u1-old", "ctx", "user", parts=["OLD QUESTION"], at=_local(12, 10)),
        _node(
            "u1", "ctx", "user", content_type="multimodal_text", at=_local(12, 10, 5),
            parts=[{"content_type": "image_asset_pointer", "asset_pointer": "sediment://file_1"}, "比较一下跑步数据"],
            metadata={"attachments": [
                {"id": "file_1", "name": "run.png", "mime_type": "image/png"},
                {"id": "file_2", "name": "plan.pdf", "mime_type": "application/pdf"},
            ]},
        ),
        _node("pre", "u1", "assistant", parts=["Let me look"], metadata={"is_thinking_preamble_message": True}, at=_local(12, 10, 6)),
        _node("thoughts", "pre", "assistant", content_type="thoughts", at=_local(12, 10, 6)),
        _node("recap", "thoughts", "assistant", content_type="reasoning_recap", at=_local(12, 10, 6)),
        _node("call", "recap", "assistant", content_type="code", recipient="api_tool.call_tool", at=_local(12, 10, 6)),
        _node("tool", "call", "tool", parts=["HEALTH DATA"], at=_local(12, 10, 6)),
        _node("a1", "tool", "assistant", parts=["心率偏高citeturn0search0。"], at=_local(12, 10, 7)),
        _node("a2", "a1", "assistant", parts=["建议休息"], at=_local(12, 10, 8)),
    ]
    return {
        "title": "比较跑步数据",
        "create_time": _local(12, 10).timestamp(),
        "current_node": "a2",
        "mapping": {node["id"]: node for node in nodes},
    }


def write_archive(store: Path) -> None:
    (store / "claude").mkdir(parents=True)
    (store / "chatgpt").mkdir(parents=True)
    (store / "claude" / "c-1.json").write_text(json.dumps({
        "provider": "claude", "id": "c-1", "tags": [], "conversation": claude_conversation(),
    }), encoding="utf-8")
    (store / "chatgpt" / "g-1.json").write_text(json.dumps({
        "provider": "chatgpt", "id": "g-1", "tags": [], "conversation": chatgpt_conversation(),
    }), encoding="utf-8")
    # Health membership can arrive through the list index without a refetch.
    (store / "index.json").write_text(json.dumps({
        "providers": {"chatgpt": {"listed": {"g-1": {"tags": ["health"]}}, "stored": {}}},
    }), encoding="utf-8")


class TestVisibleMessages(unittest.TestCase):
    def test_claude_keeps_selected_branch_text_and_file_placeholders(self):
        messages = copilot.claude_web_visible_messages(claude_conversation())
        self.assertEqual(
            [(role, text) for _, role, text in messages],
            [
                ("user", "脸肿了\n\n[Image: face.jpg]"),
                ("assistant", "可能是过敏"),
                ("user", "要去医院吗"),
                ("assistant", "先观察"),
            ],
        )
        joined = json.dumps(messages, ensure_ascii=False)
        for hidden in ("OLD BRANCH", "SECRET THOUGHT", "TOOL OUTPUT"):
            self.assertNotIn(hidden, joined)

    def test_chatgpt_drops_tools_thinking_hidden_context_and_citations(self):
        messages = copilot.merge_consecutive_web_messages(
            copilot.chatgpt_web_visible_messages(chatgpt_conversation())
        )
        self.assertEqual(
            [(role, text) for _, role, text in messages],
            [
                ("user", "[Image: run.png]\n\n比较一下跑步数据\n\n[Attachment: plan.pdf]"),
                ("assistant", "心率偏高。\n\n建议休息"),
            ],
        )
        joined = json.dumps(messages, ensure_ascii=False)
        for hidden in ("OLD QUESTION", "Let me look", "HEALTH DATA", "turn0search0"):
            self.assertNotIn(hidden, joined)


class TestDayTranscripts(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Path(self.temp.name)
        write_archive(self.store)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_messages_split_by_local_day(self):
        day1, count1, conversations1 = copilot.export_web_chat_day_transcript("claude", date(2026, 9, 12), self.store)
        day2, count2, _ = copilot.export_web_chat_day_transcript("claude", date(2026, 9, 13), self.store)
        self.assertEqual((count1, conversations1, count2), (3, 1, 1))
        self.assertIn("### Claude Web Conversation c-1 - 午餐后过敏", day1)
        self.assertIn("Source: <https://claude.ai/chat/c-1>", day1)
        self.assertIn("Henry: 脸肿了", day1)
        self.assertNotIn("先观察", day1)
        self.assertIn("Claude: 先观察", day2)

    def test_chatgpt_health_tag_comes_from_index(self):
        transcript, count, _ = copilot.export_web_chat_day_transcript("chatgpt", date(2026, 9, 12), self.store)
        self.assertEqual(count, 2)
        self.assertIn("### ChatGPT Web Conversation g-1 [Health] - 比较跑步数据", transcript)
        self.assertIn("Source: <https://chatgpt.com/c/g-1>", transcript)
        self.assertIn("ChatGPT: 心率偏高。\n\n建议休息", transcript)

    def test_missing_archive_is_empty(self):
        self.assertEqual(
            copilot.export_web_chat_day_transcript("chatgpt", date(2026, 9, 12), self.store / "absent"),
            ("", 0, 0),
        )


class TestWritebackWithWebChats(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.store = self.root / "web-chats"
        write_archive(self.store)
        self.journal = self.root / "journal" / "2026" / "09" / "2026-09-12.md"
        self.journal.parent.mkdir(parents=True)
        self.journal.write_text(MINIMAL_DIARY, encoding="utf-8")
        self.trace_dir = self.root / "journal" / "ai-conversations" / "2026" / "09"
        self.patchers = [
            patch.object(copilot, "ROOT", self.root),
            patch.object(copilot, "JOURNAL_DIR", self.root / "journal"),
            patch.object(copilot, "AI_CONVERSATIONS_DIR", self.root / "journal" / "ai-conversations"),
            patch.object(copilot, "WEB_CHATS_DIR", self.store),
            patch.object(copilot, "export_codex_day_transcript", return_value=""),
            patch.object(copilot, "export_life_claude_renderer_day_transcript", return_value=("", 0, 0)),
            patch.object(copilot, "export_claude_code_day_transcript", return_value=("", 0, 0)),
            patch.object(copilot, "export_openclaw_day_transcript", return_value=("", 0, 0)),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def test_sync_then_write_traces_and_single_links(self):
        synced = {"ok": True, "providers": {"claude": {"ok": True, "listed": 1, "fetched": 1}}}
        with patch.object(copilot, "sync_web_chats", return_value=synced) as sync, \
             redirect_stdout(io.StringIO()):
            copilot.writeback_ai_day(date(2026, 9, 12), web_chats=True)
            result = copilot.writeback_ai_day(date(2026, 9, 12), web_chats=True)
        self.assertEqual(sync.call_count, 2)
        claude_trace = (self.trace_dir / "2026-09-12-claude-web-trace.md").read_text(encoding="utf-8")
        chatgpt_trace = (self.trace_dir / "2026-09-12-chatgpt-web-trace.md").read_text(encoding="utf-8")
        self.assertIn("source: claude-web", claude_trace)
        self.assertIn("# 2026-09-12 ChatGPT Web Trace", chatgpt_trace)
        self.assertTrue(result["chatgpt_web_trace"].endswith("2026-09-12-chatgpt-web-trace.md"))
        journal = self.journal.read_text(encoding="utf-8")
        self.assertEqual(journal.count("[[2026-09-12-claude-web-trace]]"), 1)
        self.assertEqual(journal.count("[[2026-09-12-chatgpt-web-trace]]"), 1)
        self.assertIn("ChatGPT web conversations, including Health.", journal)

    def test_sync_failure_blocks_writeback(self):
        failure = copilot.WebChatsUnavailable("chatgpt: not logged in (log in again in Chrome)")
        with patch.object(copilot, "sync_web_chats", side_effect=failure):
            with self.assertRaises(copilot.WebChatsUnavailable) as caught:
                copilot.writeback_ai_day(date(2026, 9, 12), web_chats=True)
        self.assertIn("--allow-missing-web-chats", str(caught.exception))
        self.assertFalse(self.trace_dir.exists())
        self.assertEqual(self.journal.read_text(encoding="utf-8"), MINIMAL_DIARY)

    def test_allow_missing_uses_last_archive(self):
        failure = copilot.WebChatsUnavailable("Chrome closed")
        output = io.StringIO()
        with patch.object(copilot, "sync_web_chats", side_effect=failure), redirect_stdout(output):
            copilot.writeback_ai_day(date(2026, 9, 12), web_chats=True, allow_missing_web_chats=True)
        self.assertIn("warning: web chat sync failed", output.getvalue())
        self.assertTrue((self.trace_dir / "2026-09-12-claude-web-trace.md").exists())

    def test_programmatic_callers_never_sync(self):
        with patch.object(copilot, "export_codex_day_transcript", return_value="[9/12/26 1:00 PM] Henry: hi"), \
             patch.object(copilot, "sync_web_chats", side_effect=AssertionError("must not sync")), \
             redirect_stdout(io.StringIO()):
            copilot.cmd_writeback_ai_day(SimpleNamespace(date="2026-09-12"))
        self.assertFalse((self.trace_dir / "2026-09-12-claude-web-trace.md").exists())

    def test_cli_enables_web_chats_but_finalize_hook_does_not(self):
        parser = copilot.build_parser()
        self.assertTrue(parser.parse_args(["writeback-ai-day", "--date", "2026-09-12"]).web_chats)
        finalize = parser.parse_args(["finalize-ai-day", "--hook-input-file", "hook.json"])
        self.assertFalse(getattr(finalize, "web_chats", False))


class TestSyncWebChats(unittest.TestCase):
    ok_response = {
        "ok": True,
        "providers": {"claude": {"ok": True, "errors": []}, "chatgpt": {"ok": True, "errors": []}},
    }

    def test_launches_hidden_chrome_and_quits_it(self):
        with patch.object(copilot, "web_chats_host_alive", return_value=False), \
             patch.object(copilot, "chrome_is_running", return_value=False), \
             patch.object(copilot, "wait_for_web_chats_host", return_value=True), \
             patch.object(copilot.subprocess, "run") as run, \
             patch.object(copilot, "web_chats_host_request", return_value=self.ok_response), \
             patch.object(copilot, "quit_chrome") as quit_chrome:
            copilot.sync_web_chats()
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["open", "-g", "-j"])
        self.assertIn("--no-startup-window", command)
        quit_chrome.assert_called_once()

    def test_leaves_running_chrome_open(self):
        with patch.object(copilot, "web_chats_host_alive", return_value=True), \
             patch.object(copilot.subprocess, "run") as run, \
             patch.object(copilot, "web_chats_host_request", return_value=self.ok_response), \
             patch.object(copilot, "quit_chrome") as quit_chrome:
            copilot.sync_web_chats()
        run.assert_not_called()
        quit_chrome.assert_not_called()

    def test_auth_failure_is_reported(self):
        response = {
            "ok": False,
            "providers": {
                "claude": {"ok": True, "errors": []},
                "chatgpt": {"ok": False, "code": "auth_required", "message": "chatgpt: not logged in (HTTP 401)"},
            },
        }
        with patch.object(copilot, "web_chats_host_alive", return_value=True), \
             patch.object(copilot, "web_chats_host_request", return_value=response):
            with self.assertRaises(copilot.WebChatsUnavailable) as caught:
                copilot.sync_web_chats()
        self.assertIn("log in again in Chrome", str(caught.exception))

    def _rate_limited(self, newest: str) -> dict:
        return {
            "ok": True,
            "providers": {
                "claude": {"ok": True, "errors": []},
                "chatgpt": {"ok": True, "errors": [], "rate_limited": True, "pending": 37,
                            "pending_newest_update_time": newest},
            },
        }

    def test_rate_limited_leftovers_older_than_target_day_are_a_warning(self):
        day_start = datetime(2026, 9, 12).astimezone()
        with patch.object(copilot, "web_chats_host_alive", return_value=True), \
             patch.object(copilot, "web_chats_host_request",
                          return_value=self._rate_limited(_iso(_local(11, 23)))):
            result = copilot.sync_web_chats(needed_since=day_start)
        self.assertIn("37 older conversation(s)", result["warnings"][0])

    def test_rate_limited_leftovers_touching_target_day_fail(self):
        day_start = datetime(2026, 9, 12).astimezone()
        with patch.object(copilot, "web_chats_host_alive", return_value=True), \
             patch.object(copilot, "web_chats_host_request",
                          return_value=self._rate_limited(_iso(_local(12, 8)))):
            with self.assertRaises(copilot.WebChatsUnavailable) as caught:
                copilot.sync_web_chats(needed_since=day_start)
        self.assertIn("may include 2026-09-12", str(caught.exception))

    def test_extension_missing_while_chrome_runs(self):
        with patch.object(copilot, "web_chats_host_alive", return_value=False), \
             patch.object(copilot, "chrome_is_running", return_value=True), \
             patch.object(copilot, "wait_for_web_chats_host", return_value=False), \
             patch.object(copilot, "quit_chrome") as quit_chrome:
            with self.assertRaises(copilot.WebChatsUnavailable):
                copilot.sync_web_chats()
        quit_chrome.assert_not_called()


def _frame(message: dict) -> bytes:
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    return struct.pack("<I", len(body)) + body


def _read_frame(stream, timeout: float = 10) -> dict:
    ready, _, _ = select.select([stream], [], [], timeout)
    if not ready:
        raise TimeoutError("host did not send a native message")
    (length,) = struct.unpack("<I", stream.read(4))
    return json.loads(stream.read(length).decode("utf-8"))


class TestNativeHostRoundTrip(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Path(self.temp.name)
        env = {**os.environ, "LIFE_WEB_CHATS_DIR": str(self.store)}
        self.proc = subprocess.Popen(
            [sys.executable, str(HOST_SCRIPT)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            env=env,
        )
        self.send({"type": "hello", "extension_version": "test"})
        deadline = time.monotonic() + 5
        while not (self.store / "host.sock").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.patcher = patch.object(copilot, "WEB_CHATS_DIR", self.store)
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        if self.proc.poll() is None:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        self.proc.stdout.close()
        self.temp.cleanup()

    def send(self, message: dict) -> None:
        self.proc.stdin.write(_frame(message))
        self.proc.stdin.flush()

    def run_cli_sync(self, reply) -> dict:
        response: dict = {}
        client = threading.Thread(
            target=lambda: response.update(copilot.web_chats_host_request(
                {"cmd": "sync", "providers": ["chatgpt"], "timeout": 20}, timeout=30,
            )),
        )
        client.start()
        request = _read_frame(self.proc.stdout)
        reply(request)
        client.join(timeout=30)
        return {"request": request, "response": response}

    def test_sync_stores_conversations_and_reports_known_versions(self):
        conversation = chatgpt_conversation()

        def first_reply(request):
            rid = request["request_id"]
            self.send({"type": "index", "request_id": rid, "provider": "chatgpt", "items": [
                {"id": "g-1", "update_time": "2026-09-12T02:08:00Z", "title": "比较跑步数据", "tags": ["health"]},
            ]})
            self.send({"type": "conversation", "request_id": rid, "provider": "chatgpt", "id": "g-1",
                       "update_time": "2026-09-12T02:08:00Z", "tags": ["health"], "conversation": conversation})
            self.send({"type": "conversation", "request_id": rid, "provider": "chatgpt", "id": "../escape",
                       "update_time": "x", "conversation": {}})
            self.send({"type": "done", "request_id": rid, "ok": True,
                       "providers": {"chatgpt": {"ok": True, "listed": 1, "fetched": 1, "errors": []}}})

        first = self.run_cli_sync(first_reply)
        self.assertEqual(first["request"]["type"], "sync")
        self.assertEqual(first["request"]["providers"], ["chatgpt"])
        self.assertEqual(first["request"]["known"]["chatgpt"], {})
        self.assertTrue(first["response"]["ok"])
        stored = json.loads((self.store / "chatgpt" / "g-1.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["conversation"]["title"], "比较跑步数据")
        self.assertFalse(any(self.store.rglob("escape*")))

        def second_reply(request):
            self.send({"type": "done", "request_id": request["request_id"], "ok": True,
                       "providers": {"chatgpt": {"ok": True, "listed": 1, "fetched": 0, "errors": []}}})

        second = self.run_cli_sync(second_reply)
        self.assertEqual(second["request"]["known"]["chatgpt"], {"g-1": "2026-09-12T02:08:00Z"})
        self.assertTrue(copilot.web_chats_host_alive())

        index = copilot.load_web_chats_index(self.store)
        self.assertTrue(index["providers"]["chatgpt"]["last_success_at"])
        transcript, _, _ = copilot.export_web_chat_day_transcript("chatgpt", date(2026, 9, 12), self.store)
        self.assertIn("[Health]", transcript)

        self.proc.stdin.close()
        self.proc.wait(timeout=5)
        self.assertFalse((self.store / "host.sock").exists())

    def test_reload_command_is_forwarded_to_extension(self):
        response = copilot.web_chats_host_request({"cmd": "reload_extension"}, timeout=10)
        self.assertEqual(response, {"ok": True, "previous_extension_version": "test"})
        self.assertEqual(_read_frame(self.proc.stdout), {"type": "reload"})


if __name__ == "__main__":
    unittest.main()
