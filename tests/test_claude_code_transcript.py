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
