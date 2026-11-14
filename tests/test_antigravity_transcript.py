"""Tests for Antigravity transcript archiving, source guard, timeline, and writeback."""

from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import copilot

DAY = date(2026, 11, 14)
MINIMAL_DIARY = textwrap.dedent("""\
    #diary
    # 📅 2026-11-14
    ## 💭 Thoughts & Reflections

    手写内容。

    ## 💬 From Kai

    ## What Life Copilot Said
""")


def _iso(hour: int, minute: int, day: int = 14) -> str:
    return datetime(2026, 11, day, hour, minute).astimezone().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_steps(brain_dir: Path, conv_id: str, steps: list[dict], *, filename: str = "transcript_full.jsonl") -> None:
    logs_dir = brain_dir / conv_id / ".system_generated" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.joinpath(filename).write_text(
        "\n".join(json.dumps(step, ensure_ascii=False) for step in steps) + "\n",
        encoding="utf-8",
    )


def _create_summaries_db(db_path: Path, rows: list[tuple]) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE conversation_summaries (
                conversation_id TEXT PRIMARY KEY,
                title TEXT,
                workspace_uris TEXT,
                status TEXT,
                source TEXT,
                agent_name TEXT,
                parent_conversation_id TEXT,
                nesting_depth INTEGER
            )
            """
        )
        conn.executemany(
            "INSERT INTO conversation_summaries VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def _user_step(content: str, ts: str, *, media: list[dict] | None = None) -> dict:
    step: dict = {"source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": ts, "content": content}
    if media is not None:
        step["media"] = media
    return step


def _model_step(content: str, ts: str, *, tool_calls: list[dict] | None = None) -> dict:
    step: dict = {"source": "MODEL", "type": "PLANNER_RESPONSE", "created_at": ts, "content": content}
    if tool_calls is not None:
        step["tool_calls"] = tool_calls
    return step


class TestAntigravityTranscript(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.brain_dir = self.root / "brain"
        self.brain_dir.mkdir()
        self.db_path = self.root / "conversation_summaries.db"

        # Session 1 (later in the day): quoted selection, prefix feedback, media, tool filtering.
        _write_steps(
            self.brain_dir,
            "11111111-aaaa-4111-8111-111111111111",
            [
                {"source": "SYSTEM", "type": "TASK_BOUNDARY", "created_at": _iso(14, 0), "content": "ignored"},
                _user_step(
                    "User submitted feedback on artifact.\n"
                    "<USER_REQUEST>\n"
                    "<USER_SETTINGS_CHANGE>\nsetting=1\n</USER_SETTINGS_CHANGE>\n"
                    "请检查这段计算逻辑。\n"
                    "</USER_REQUEST>\n"
                    "<ADDITIONAL_METADATA>\n"
                    "@[Quote] is a [Text Block]:\n"
                    "def f(x):\n"
                    "    return x + 1\n"
                    "@[file.py] is a [File].\n"
                    "</ADDITIONAL_METADATA>",
                    _iso(14, 5),
                    media=[
                        {"mime_type": "image/png", "uri": "file:///tmp/screenshot.png"},
                        {"mime_type": "audio/mpeg", "uri": "file:///tmp/voice.mp3"},
                    ],
                ),
                _model_step(
                    "Let me inspect file.py first.",
                    _iso(14, 6),
                    tool_calls=[{"name": "default_api:read_file", "arguments": {}}],
                ),
                _model_step(
                    "Which option do you prefer?",
                    _iso(14, 7),
                    tool_calls=[{"name": "default_api:ask_question", "arguments": {}}],
                ),
                _model_step("已经检查完毕，逻辑没问题。", _iso(14, 8), tool_calls=[]),
            ],
        )
        # Session 2 (earlier in the day): multi-day, only step on DAY should be included.
        _write_steps(
            self.brain_dir,
            "22222222-bbbb-4222-8222-222222222222",
            [
                _user_step("<USER_REQUEST>\n昨天的消息\n</USER_REQUEST>", _iso(22, 0, day=13)),
                _model_step("昨天的回复", _iso(22, 1, day=13), tool_calls=[]),
                _user_step("<USER_REQUEST>\n早安，继续讨论\n</USER_REQUEST>", _iso(9, 10, day=14)),
                _model_step("继续，现在在看实现。", _iso(9, 12, day=14), tool_calls=[]),
            ],
        )
        # Session 3: subagent marked via SQLite metadata.
        _write_steps(
            self.brain_dir,
            "33333333-cccc-4333-8333-333333333333",
            [
                _user_step("<USER_REQUEST>\nSubagent internal task\n</USER_REQUEST>", _iso(10, 0)),
                _model_step("SUBAGENT_SQLITE_REPLY", _iso(10, 1), tool_calls=[]),
            ],
        )
        # Session 4: subagent marked only by step-0 SYSTEM_MESSAGE (not in SQLite).
        _write_steps(
            self.brain_dir,
            "44444444-dddd-4444-8444-444444444444",
            [
                {"source": "SYSTEM", "type": "SYSTEM_MESSAGE", "created_at": _iso(10, 30), "content": "boot"},
                _user_step("<USER_REQUEST>\nFallback subagent prompt\n</USER_REQUEST>", _iso(10, 31)),
                _model_step("SUBAGENT_FALLBACK_REPLY", _iso(10, 32), tool_calls=[]),
            ],
        )
        # Session 5: unanswered single-prompt stub.
        _write_steps(
            self.brain_dir,
            "55555555-eeee-4555-8555-555555555555",
            [
                _user_step("<USER_REQUEST>\nUnanswered prompt\n</USER_REQUEST>", _iso(11, 0)),
            ],
        )

        _create_summaries_db(
            self.db_path,
            [
                (
                    "11111111-aaaa-4111-8111-111111111111",
                    "Logic Review",
                    json.dumps(["file:///vault/Life"]),
                    "IDLE",
                    "USER",
                    "",
                    "",
                    0,
                ),
                (
                    "22222222-bbbb-4222-8222-222222222222",
                    "Morning Follow-up",
                    json.dumps(["file:///vault/Life"]),
                    "IDLE",
                    "USER",
                    "",
                    "",
                    0,
                ),
                (
                    "33333333-cccc-4333-8333-333333333333",
                    "Subagent Task",
                    json.dumps(["file:///vault/Life"]),
                    "IDLE",
                    "SUBAGENT",
                    "research",
                    "11111111-aaaa-4111-8111-111111111111",
                    1,
                ),
            ],
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_export_cleans_requests_quotes_media_tools_and_excludes_subagents(self) -> None:
        transcript, msg_count, session_count = copilot.export_antigravity_day_transcript(
            DAY,
            brain_dir=self.brain_dir,
            summaries_db=self.db_path,
        )
        self.assertEqual((session_count, msg_count), (2, 5))
        # Ordered chronologically: session 22222222 (09:10) before 11111111 (14:05).
        pos_early = transcript.index("### Antigravity Session 22222222-bbbb-4222-8222-222222222222 - Morning Follow-up")
        pos_late = transcript.index("### Antigravity Session 11111111-aaaa-4111-8111-111111111111 - Logic Review")
        self.assertLess(pos_early, pos_late)

        self.assertIn("User submitted feedback on artifact.", transcript)
        self.assertIn("请检查这段计算逻辑。", transcript)
        self.assertIn("Attachments:\n  - Selected text:\n    > def f(x):\n    >     return x + 1", transcript)
        self.assertIn("[Image: screenshot.png]\n[Audio: voice.mp3]", transcript)
        self.assertIn("Which option do you prefer?", transcript)
        self.assertIn("已经检查完毕，逻辑没问题。", transcript)

        for excluded in (
            "setting=1",
            "Let me inspect file.py first.",
            "昨天的消息",
            "SUBAGENT_SQLITE_REPLY",
            "SUBAGENT_FALLBACK_REPLY",
            "Unanswered prompt",
        ):
            self.assertNotIn(excluded, transcript)

    def test_source_records_satisfy_trace_guard(self) -> None:
        transcript, _, _ = copilot.export_antigravity_day_transcript(
            DAY,
            brain_dir=self.brain_dir,
            summaries_db=self.db_path,
        )
        records = copilot.antigravity_day_source_records(
            DAY,
            brain_dir=self.brain_dir,
            summaries_db=self.db_path,
        )
        trace_dir = self.root / "journal" / "ai-conversations" / "2026" / "11"
        trace_path = trace_dir / "2026-11-14-antigravity-trace.md"
        header = ["---", f"date: {DAY.isoformat()}", "source: antigravity", "---", ""]
        with patch.object(copilot, "ROOT", self.root):
            copilot.write_ai_trace(
                trace_path,
                header,
                transcript,
                "antigravity",
                lambda: records,
            )
            written = trace_path.read_text(encoding="utf-8")
            # Rewrite the same trace with source guard enabled; nothing should be flagged missing.
            with patch("sys.stderr", new_callable=io.StringIO) as err:
                kept = copilot.write_ai_trace(
                    trace_path,
                    header,
                    transcript,
                    "antigravity",
                    lambda: records,
                )
            self.assertEqual(kept, 0)
            self.assertEqual(err.getvalue(), "")
            self.assertEqual(trace_path.read_text(encoding="utf-8"), written)


class TestAntigravityAndGeminiTimelineWriteback(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.journal = self.root / "journal" / "2026" / "11" / "2026-11-14.md"
        self.trace_dir = self.root / "journal" / "ai-conversations" / "2026" / "11"
        self.brain_dir = self.root / "antigravity" / "brain"
        self.brain_dir.mkdir(parents=True)
        self.db_path = self.root / "antigravity" / "conversation_summaries.db"
        _write_steps(
            self.brain_dir,
            "aaaabbbb-1111-4111-8111-111111111111",
            [
                _user_step("<USER_REQUEST>\n整理每日同步规则\n</USER_REQUEST>", _iso(15, 0)),
                _model_step("已经把同步流程补全。", _iso(15, 2), tool_calls=[]),
            ],
        )
        _create_summaries_db(
            self.db_path,
            [(
                "aaaabbbb-1111-4111-8111-111111111111",
                "Daily Sync Rules",
                json.dumps([self.root.as_uri()]),
                "IDLE",
                "USER",
                "",
                "",
                0,
            )],
        )

        self.patchers = [
            patch.object(copilot, "ROOT", self.root),
            patch.object(copilot, "JOURNAL_DIR", self.root / "journal"),
            patch.object(copilot, "AI_CONVERSATIONS_DIR", self.root / "journal" / "ai-conversations"),
            patch.object(copilot, "ANTIGRAVITY_BRAIN_DIR", self.brain_dir),
            patch.object(copilot, "ANTIGRAVITY_SUMMARIES_DB", self.db_path),
            patch.object(copilot, "export_codex_day_transcript", return_value=""),
            patch.object(copilot, "codex_day_source_records", return_value=[]),
            patch.object(copilot, "export_life_claude_renderer_day_transcript", return_value=("", 0, 0)),
            patch.object(copilot, "export_claude_code_day_transcript", return_value=("", 0, 0)),
            patch.object(copilot, "export_openclaw_day_transcript", return_value=("", 0, 0)),
            patch.object(copilot, "openclaw_day_source_records", return_value=[]),
            patch.object(copilot, "WEB_CHATS_DIR", self.root / "absent-web-chats"),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def test_timeline_parses_antigravity_and_gemini_web_sessions(self) -> None:
        self.trace_dir.mkdir(parents=True)
        (self.trace_dir / "2026-11-14-antigravity-trace.md").write_text(
            "---\ndate: 2026-11-14\nsource: antigravity\n---\n\n"
            "### Antigravity Session aaaabbbb-1111-4111-8111-111111111111 - Daily Sync Rules\n\n"
            f"[{copilot.format_chat_timestamp(_iso(15, 0))}] Henry: 整理每日同步规则\n\n"
            f"[{copilot.format_chat_timestamp(_iso(15, 2))}] Antigravity: 已经把同步流程补全。\n",
            encoding="utf-8",
        )
        (self.trace_dir / "2026-11-14-gemini-web-trace.md").write_text(
            "---\ndate: 2026-11-14\nsource: gemini-web\n---\n\n"
            "### Gemini Web Conversation 0f908f0cfc9cf111 - Reconnecting After a While\n\n"
            "Source: <https://gemini.google.com/app/0f908f0cfc9cf111>\n\n"
            f"[{copilot.format_chat_timestamp(_iso(16, 0))}] Henry: Check Chinese level\n\n"
            f"[{copilot.format_chat_timestamp(_iso(16, 1))}] Gemini: Steadily better.\n",
            encoding="utf-8",
        )
        timeline = copilot.render_day_timeline(DAY)
        self.assertIn("15:00–15:02 · Antigravity aaaabbbb `Daily Sync Rules` · Henry 1, AI 1 · `整理每日同步规则`", timeline)
        self.assertIn("16:00–16:01 · Gemini Web 0f908f0c `Reconnecting After a While` · Henry 1, AI 1 · `Check Chinese level`", timeline)

    def test_writeback_and_refresh_write_antigravity_trace(self) -> None:
        # refresh-ai-day writes trace + timeline without requiring or touching journal.
        args = copilot.build_parser().parse_args(["refresh-ai-day", "--date", "2026-11-14", "--no-openclaw"])
        with redirect_stdout(io.StringIO()):
            args.func(args)
        ag_trace = self.trace_dir / "2026-11-14-antigravity-trace.md"
        self.assertTrue(ag_trace.exists())
        self.assertIn("### Antigravity Session aaaabbbb-1111-4111-8111-111111111111 - Daily Sync Rules", ag_trace.read_text(encoding="utf-8"))
        self.assertTrue((self.trace_dir / "2026-11-14-timeline.md").exists())
        self.assertFalse(self.journal.exists())

        # writeback-ai-day links the antigravity trace into ## From Kai.
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        self.journal.write_text(MINIMAL_DIARY, encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            result = copilot.writeback_ai_day(DAY)
        self.assertEqual(result["antigravity_trace"], str(ag_trace))
        journal_text = self.journal.read_text(encoding="utf-8")
        self.assertIn("- [[2026-11-14-antigravity-trace]]：Antigravity sessions.", journal_text)


if __name__ == "__main__":
    unittest.main()
