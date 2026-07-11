"""Focused tests for safe, readable Codex transcript exports."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

from scripts.copilot import (
    clean_codex_user_text,
    codex_session_is_primary_thread,
    export_codex_day_transcript,
    export_codex_transcript,
    sanitize_codex_transcript_text,
    summarize_codex_contexts,
)


class TestCodexContextSummaries(unittest.TestCase):

    def test_plain_user_text_is_unchanged(self):
        text = "请帮我看看这份材料。"
        self.assertEqual(clean_codex_user_text(text), text)

    def test_file_content_is_replaced_with_path_marker(self):
        text = (
            '<context>\n<file_context path="inbox/example.pdf">\n'
            "%PDF-1.7\nstream\x00\x01\x02garbage\n"
            "</file_context>\n</context>\n\n"
            "这份文件里我应该了解什么？"
        )
        cleaned = clean_codex_user_text(text)

        self.assertIn(
            "> Attached file: `inbox/example.pdf` (content omitted from archive).",
            cleaned,
        )
        self.assertIn("这份文件里我应该了解什么？", cleaned)
        self.assertNotIn("%PDF", cleaned)
        self.assertNotIn("stream", cleaned)
        self.assertNotIn("\x00", cleaned)

    def test_multiple_paths_keep_order_and_are_deduplicated(self):
        text = (
            '<context><file_context path="a.md">A</file_context>'
            '<file_context path="b.txt">B</file_context>'
            '<file_context path="a.md">A again</file_context></context>'
            "question"
        )
        cleaned = summarize_codex_contexts(text)

        self.assertEqual(cleaned.count("Attached file: `a.md`"), 1)
        self.assertEqual(cleaned.count("Attached file: `b.txt`"), 1)
        self.assertLess(cleaned.index("`a.md`"), cleaned.index("`b.txt`"))
        self.assertTrue(cleaned.rstrip().endswith("question"))

    def test_context_without_file_paths_is_omitted(self):
        text = "<context><metadata>machine-only</metadata></context>actual request"
        self.assertEqual(clean_codex_user_text(text), "actual request")

    def test_agents_bootstrap_is_still_removed(self):
        text = (
            "# AGENTS.md instructions for /tmp\nbootstrap\n"
            "<environment_context>cwd</environment_context>\n"
            "actual request"
        )
        self.assertEqual(clean_codex_user_text(text), "actual request")


class TestCodexTranscriptSanitizing(unittest.TestCase):

    def test_normalizes_newlines_and_removes_terminal_controls(self):
        text = "start\r\n\x1b[0G\x1b[2Kstatus\x00\x07\rfinish\x7f"
        self.assertEqual(sanitize_codex_transcript_text(text), "start\nstatus\nfinish")

    def test_exported_messages_are_safe_and_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "rollout-test.jsonl"
            records = [
                {
                    "timestamp": "2026-07-09T09:01:00Z",
                    "type": "session_meta",
                    "payload": {"type": "session_meta", "id": "thread-test"},
                },
                {
                    "timestamp": "2026-07-09T09:01:00Z",
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": (
                                    '<context><file_context path="inbox/test.pdf">'
                                    "%PDF-1.7\x00\x1b[31mgarbage"
                                    "</file_context></context>What matters?"
                                ),
                            }
                        ],
                    },
                },
                {
                    "timestamp": "2026-07-09T09:02:00Z",
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": "\x1b[2KReadable answer\x00"}
                        ],
                    },
                },
            ]
            session.write_text(
                "\n".join(json.dumps(record, ensure_ascii=False) for record in records),
                encoding="utf-8",
            )

            transcript = export_codex_transcript(session)

        self.assertIn("Attached file: `inbox/test.pdf`", transcript)
        self.assertIn("What matters?", transcript)
        self.assertIn("Readable answer", transcript)
        self.assertNotIn("%PDF", transcript)
        self.assertNotIn("\x00", transcript)
        self.assertNotIn("\x1b", transcript)


class TestCodexDayArchiveSessionFiltering(unittest.TestCase):

    @staticmethod
    def _write_session(path: Path, thread_id: str, thread_source: str, text: str) -> None:
        records = [
            {
                "timestamp": "2026-07-09T09:00:00Z",
                "type": "session_meta",
                "payload": {"id": thread_id, "thread_source": thread_source},
            },
            {
                "timestamp": "2026-07-09T09:01:00Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": text}],
                },
            },
        ]
        path.write_text(
            "\n".join(json.dumps(record, ensure_ascii=False) for record in records),
            encoding="utf-8",
        )

    def test_primary_user_thread_is_included(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "primary.jsonl"
            session.write_text(
                json.dumps({
                    "type": "session_meta",
                    "payload": {"id": "primary", "thread_source": "user"},
                }),
                encoding="utf-8",
            )
            self.assertTrue(codex_session_is_primary_thread(session))

    def test_internal_subagent_thread_is_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "reviewer.jsonl"
            session.write_text(
                json.dumps({
                    "type": "session_meta",
                    "payload": {"id": "reviewer", "thread_source": "subagent"},
                }),
                encoding="utf-8",
            )
            self.assertFalse(codex_session_is_primary_thread(session))

    def test_legacy_session_without_thread_source_is_included(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "legacy.jsonl"
            session.write_text(
                json.dumps({"type": "session_meta", "payload": {"id": "legacy"}}),
                encoding="utf-8",
            )
            self.assertTrue(codex_session_is_primary_thread(session))

    def test_day_archive_excludes_internal_session_transcripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary = Path(tmp) / "primary.jsonl"
            reviewer = Path(tmp) / "reviewer.jsonl"
            self._write_session(primary, "primary", "user", "real user message")
            self._write_session(reviewer, "reviewer", "subagent", "duplicated review transcript")

            with patch(
                "scripts.copilot.codex_session_files_for_date_range",
                return_value=[primary, reviewer],
            ):
                transcript = export_codex_day_transcript(date(2026, 7, 9))

        self.assertIn("real user message", transcript)
        self.assertNotIn("duplicated review transcript", transcript)


if __name__ == "__main__":
    unittest.main()
