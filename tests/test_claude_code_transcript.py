"""Tests for native Claude Code daily transcript ingestion."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import copilot


def _iso(local_dt: datetime) -> str:
    return local_dt.astimezone().isoformat()


def _write_session(projects_dir: Path, session_id: str, records: list[dict]) -> Path:
    projects_dir.mkdir(parents=True, exist_ok=True)
    path = projects_dir / f"{session_id}.jsonl"
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )
    return path


def _user(text: object, ts: str, *, sidechain: bool = False) -> dict:
    return {
        "type": "user",
        "timestamp": ts,
        "isSidechain": sidechain,
        "message": {"role": "user", "content": text},
    }


def _assistant(parts: list[dict], ts: str, *, sidechain: bool = False) -> dict:
    return {
        "type": "assistant",
        "timestamp": ts,
        "isSidechain": sidechain,
        "message": {"role": "assistant", "content": parts},
    }


def _with_uuid(uuid: str, record: dict) -> dict:
    return {**record, "uuid": uuid}


class TestClaudeCodeTranscript(unittest.TestCase):
    def test_exports_only_visible_dialogue_for_target_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            projects = root / "projects"
            renderer = root / "history.json"
            renderer.write_text("[]", encoding="utf-8")
            target_ts = _iso(datetime(2026, 6, 6, 10, 0))
            next_ts = _iso(datetime(2026, 6, 7, 10, 0))
            _write_session(projects, "session-a", [
                _user("真实提问", target_ts),
                _assistant([
                    {"type": "thinking", "thinking": "hidden chain"},
                    {"type": "tool_use", "name": "Read", "input": {"path": "secret"}},
                    {"type": "text", "text": "可见回答"},
                ], target_ts),
                _user([{"type": "tool_result", "content": "tool output"}], target_ts),
                _user("sidechain prompt", target_ts, sidechain=True),
                _assistant([{"type": "text", "text": "sidechain answer"}], target_ts, sidechain=True),
                _user("明天的问题", next_ts),
                _assistant([{"type": "text", "text": "明天的回答"}], next_ts),
                {"type": "custom-title", "customTitle": "原生 CLI 会话"},
            ])

            with patch.object(copilot, "CLAUDIAN_SESSIONS_DIR", root / "claudian"):
                text, message_count, session_count = copilot.export_claude_code_day_transcript(
                    date(2026, 6, 6),
                    projects_dir=projects,
                    renderer_history_path=renderer,
                )

            self.assertIn("Claude Code Session session-a - 原生 CLI 会话", text)
            self.assertIn("真实提问", text)
            self.assertIn("可见回答", text)
            self.assertNotIn("hidden chain", text)
            self.assertNotIn("tool output", text)
            self.assertNotIn("sidechain", text)
            self.assertNotIn("明天", text)
            self.assertEqual(message_count, 2)
            self.assertEqual(session_count, 1)

    def test_keeps_prompts_sent_as_content_parts_with_pasted_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            projects = root / "projects"
            renderer = root / "history.json"
            renderer.write_text("[]", encoding="utf-8")
            ts = _iso(datetime(2026, 9, 18, 15, 18))
            image = {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="},
            }
            meta_note = _user([{"type": "text", "text": "[Image: source: /private/tmp/paste.png]"}], ts)
            meta_note["isMeta"] = True
            resize_note = _user("[Image: original 2250x1110, displayed at 2000x987.]", ts)
            resize_note["isMeta"] = True
            _write_session(projects, "image-session", [
                _user([image, {"type": "text", "text": "  图是会议白板  "}], ts),
                meta_note,
                resize_note,
                _assistant([{"type": "text", "text": "看到了"}], ts),
                _user([image, image, {"type": "text", "text": "两张截图"}], ts),
                _user([{"type": "text", "text": "prompt sent as parts"}], ts),
                _user([{"type": "text", "text": "[Request interrupted by user]"}], ts),
                _user([image], ts),
                _user([
                    {"type": "tool_result", "content": "tool output"},
                    {"type": "text", "text": "[Request interrupted by user for tool use]"},
                ], ts),
            ])

            with patch.object(copilot, "CLAUDIAN_SESSIONS_DIR", root / "claudian"):
                text, message_count, session_count = copilot.export_claude_code_day_transcript(
                    date(2026, 9, 18),
                    projects_dir=projects,
                    renderer_history_path=renderer,
                )

            self.assertIn("Henry: [Image]\n\n图是会议白板\n", text)
            self.assertIn("Henry: [Image]\n\n[Image]\n\n两张截图\n", text)
            self.assertIn("Henry: prompt sent as parts", text)
            self.assertNotIn("iVBORw0KGgo", text)
            self.assertNotIn("/private/tmp", text)
            self.assertNotIn("displayed at", text)
            self.assertNotIn("Request interrupted", text)
            self.assertNotIn("tool output", text)
            self.assertEqual(message_count, 4)
            self.assertEqual(session_count, 1)

    def test_drops_task_notifications_and_client_error_notices(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            projects = root / "projects"
            renderer = root / "history.json"
            renderer.write_text("[]", encoding="utf-8")
            ts = _iso(datetime(2026, 9, 7, 22, 56))
            limit_notice = _assistant(
                [{"type": "text", "text": "You've hit your session limit · resets 1am"}], ts
            )
            limit_notice["isApiErrorMessage"] = True
            limit_notice["message"]["model"] = "<synthetic>"
            _write_session(projects, "notices", [
                _user("更新一下索引", ts),
                _assistant([{"type": "text", "text": "开始更新"}], ts),
                _user(
                    "<task-notification>\n<task-id>task-1</task-id>\n"
                    "<status>completed</status>\n</task-notification>",
                    ts,
                ),
                limit_notice,
            ])

            with patch.object(copilot, "CLAUDIAN_SESSIONS_DIR", root / "claudian"):
                text, message_count, _ = copilot.export_claude_code_day_transcript(
                    date(2026, 9, 7),
                    projects_dir=projects,
                    renderer_history_path=renderer,
                )

            self.assertIn("Henry: 更新一下索引", text)
            self.assertIn("Claude: 开始更新", text)
            self.assertNotIn("task-notification", text)
            self.assertNotIn("session limit", text)
            self.assertEqual(message_count, 2)

    def test_excludes_renderer_session_and_abandoned_user_only_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            projects = root / "projects"
            ts = _iso(datetime(2026, 6, 6, 10, 0))
            _write_session(projects, "renderer-session", [
                _user("duplicated user", ts),
                _assistant([{"type": "text", "text": "duplicated answer"}], ts),
            ])
            _write_session(projects, "abandoned-session", [_user("unfinished prompt", ts)])
            renderer = root / "history.json"
            renderer.write_text(json.dumps([{
                "sessionId": "renderer-session",
                "messages": [],
            }]), encoding="utf-8")

            with patch.object(copilot, "CLAUDIAN_SESSIONS_DIR", root / "claudian"):
                text, message_count, session_count = copilot.export_claude_code_day_transcript(
                    date(2026, 6, 6),
                    projects_dir=projects,
                    renderer_history_path=renderer,
                )

            self.assertEqual(text, "")
            self.assertEqual(message_count, 0)
            self.assertEqual(session_count, 0)

    def test_forked_session_renders_shared_messages_once_in_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            projects = root / "projects"
            renderer = root / "history.json"
            renderer.write_text("[]", encoding="utf-8")
            first_ts = _iso(datetime(2026, 6, 6, 10, 0))
            draft_ts = _iso(datetime(2026, 6, 6, 11, 0))
            fork_ts = _iso(datetime(2026, 6, 6, 11, 5))
            title = {"type": "custom-title", "customTitle": "读书讨论"}
            history = [
                _with_uuid("u-1", _user("第一个问题", first_ts)),
                _with_uuid("a-1", _assistant([{"type": "text", "text": "第一个回答"}], first_ts)),
            ]

            def fork(*records: dict) -> list[dict]:
                # A fork writes its own first record, then copies the parent's
                # records with their uuids and timestamps.
                return [title, {"type": "queue-operation", "timestamp": fork_ts}, *history, *records]

            # Named so that sorting by file name would put a fork first.
            _write_session(projects, "b-original", [
                {"type": "queue-operation", "timestamp": first_ts},
                *history,
                _with_uuid("u-2", _user("草稿问题", draft_ts)),
                title,
            ])
            _write_session(projects, "a-edited-fork", fork(
                _with_uuid("u-3", _user("改写后的问题", fork_ts)),
                _with_uuid("a-3", _assistant([{"type": "text", "text": "改写后的回答"}], fork_ts)),
            ))
            _write_session(projects, "c-copy-only-fork", fork())
            _write_session(projects, "d-unanswered-fork", fork(
                _with_uuid("u-4", _user("没等到回答", fork_ts)),
            ))

            with patch.object(copilot, "CLAUDIAN_SESSIONS_DIR", root / "claudian"):
                text, message_count, session_count = copilot.export_claude_code_day_transcript(
                    date(2026, 6, 6),
                    projects_dir=projects,
                    renderer_history_path=renderer,
                )

            self.assertEqual(text, "\n\n".join([
                "### Claude Code Session b-original - 读书讨论",
                "[6/6/26 10:00 AM] Henry: 第一个问题",
                "[6/6/26 10:00 AM] Claude: 第一个回答",
                "[6/6/26 11:00 AM] Henry: 草稿问题",
                "### Claude Code Session a-edited-fork - 读书讨论 (branched from b-original)",
                "[6/6/26 11:05 AM] Henry: 改写后的问题",
                "[6/6/26 11:05 AM] Claude: 改写后的回答",
            ]) + "\n")
            self.assertEqual(message_count, 5)
            self.assertEqual(session_count, 2)

    def test_writeback_creates_trace_and_idempotent_from_kai_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal_dir = root / "journal" / "2026" / "06"
            journal_dir.mkdir(parents=True)
            journal_path = journal_dir / "2026-06-06.md"
            journal_path.write_text(
                "# 2026-06-06\n\n## 💬 From Kai\n\n## End\n",
                encoding="utf-8",
            )
            projects = root / "projects"
            ts = _iso(datetime(2026, 6, 6, 10, 0))
            _write_session(projects, "native-session", [
                _user("hello from CLI", ts),
                _assistant([{"type": "text", "text": "hello from Claude"}], ts),
            ])
            renderer = root / "history.json"
            renderer.write_text("[]", encoding="utf-8")

            common_patches = (
                patch.object(copilot, "ROOT", root),
                patch.object(copilot, "JOURNAL_DIR", root / "journal"),
                patch.object(copilot, "AI_CONVERSATIONS_DIR", root / "journal" / "ai-conversations"),
                patch.object(copilot, "CLAUDE_PROJECTS_DIR", projects),
                patch.object(copilot, "CLAUDIAN_SESSIONS_DIR", root / "claudian"),
                patch.object(copilot, "LIFE_CLAUDE_RENDERER_HISTORY", renderer),
                patch.object(copilot, "export_codex_day_transcript", return_value=""),
                patch.object(copilot, "export_openclaw_day_transcript", return_value=("", 0, 0)),
            )
            for context in common_patches:
                context.start()
            try:
                with redirect_stdout(io.StringIO()):
                    copilot.cmd_writeback_ai_day(SimpleNamespace(date="2026-06-06"))
                    copilot.cmd_writeback_ai_day(SimpleNamespace(date="2026-06-06"))
            finally:
                for context in reversed(common_patches):
                    context.stop()

            trace_path = journal_dir / "2026-06-06-claude-code-trace.md"
            # Trace files live under journal/ai-conversations, not beside the diary.
            trace_path = root / "journal" / "ai-conversations" / "2026" / "06" / trace_path.name
            trace = trace_path.read_text(encoding="utf-8")
            journal = journal_path.read_text(encoding="utf-8")
            self.assertIn("source: claude-code", trace)
            self.assertIn("hello from CLI", trace)
            self.assertIn("hello from Claude", trace)
            self.assertEqual(journal.count("[[2026-06-06-claude-code-trace]]"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
