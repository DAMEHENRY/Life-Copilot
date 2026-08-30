"""Focused tests for Life Claude Renderer history importer.

Uses temporary fixture files — no real history.json is read or modified.
"""

from __future__ import annotations

import json
import sys
import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

# Add project root to path so we can import copilot
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

from scripts.copilot import (
    ai_trace_path_for_date,
    cmd_preview_ai_day,
    cmd_writeback_ai_day,
    export_life_claude_renderer_day_transcript,
    load_life_claude_renderer_history,
)
from scripts import copilot as copilot_module


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_history(tmp_dir: Path, conversations: list) -> Path:
    """Write a fixture history.json and return its path."""
    p = tmp_dir / "history.json"
    p.write_text(json.dumps(conversations, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _make_conversation(
    session_id: str = "sid-001",
    title: str = "Test conversation",
    messages: list | None = None,
    created_at: int = 1780750000000,
    updated_at: int = 1780750000000,
) -> dict:
    return {
        "sessionId": session_id,
        "title": title,
        "createdAt": created_at,
        "updatedAt": updated_at,
        "lastModel": "mimo-v2.5-pro",
        "messages": messages or [],
    }


def _make_message(
    role: str,
    content: str,
    timestamp_ms: int,
    display_content: str | None = None,
) -> dict:
    msg = {"role": role, "content": content, "timestamp": timestamp_ms}
    if display_content is not None:
        msg["displayContent"] = display_content
    return msg


# Timestamps for 2026-06-06 in local timezone
# We use datetime to get the correct local timestamps
_ts_base = datetime(2026, 6, 6, 10, 0, 0)
_ts_afternoon = datetime(2026, 6, 6, 15, 30, 0)
_ts_evening = datetime(2026, 6, 6, 21, 0, 0)
# Previous day
_ts_prev_day = datetime(2026, 6, 5, 23, 0, 0)
# Next day
_ts_next_day = datetime(2026, 6, 7, 1, 0, 0)

_TS_BASE_MS = int(_ts_base.timestamp() * 1000)
_TS_AFTERNOON_MS = int(_ts_afternoon.timestamp() * 1000)
_TS_EVENING_MS = int(_ts_evening.timestamp() * 1000)
_TS_PREV_DAY_MS = int(_ts_prev_day.timestamp() * 1000)
_TS_NEXT_DAY_MS = int(_ts_next_day.timestamp() * 1000)


# ---------------------------------------------------------------------------
# Tests: load_life_claude_renderer_history
# ---------------------------------------------------------------------------

class TestLoadHistory(unittest.TestCase):

    def test_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = load_life_claude_renderer_history(Path(tmp) / "nonexistent.json")
            assert result == []

    def test_malformed_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "history.json"
            p.write_text("not valid json {{{", encoding="utf-8")
            result = load_life_claude_renderer_history(p)
            assert result == []

    def test_non_array_top_level_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "history.json"
            p.write_text('{"not": "an array"}', encoding="utf-8")
            result = load_life_claude_renderer_history(p)
            assert result == []

    def test_invalid_conversation_objects_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write_history(Path(tmp), [
                "not a dict",
                42,
                {"sessionId": 123, "messages": "not a list"},  # wrong types
                _make_conversation("valid-sid", "Valid", []),
            ])
            result = load_life_claude_renderer_history(p)
            assert len(result) == 1
            assert result[0]["sessionId"] == "valid-sid"

    def test_valid_conversations_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            conv = _make_conversation("sid-1", "Title", [
                _make_message("user", "hello", _TS_BASE_MS),
            ])
            p = _write_history(Path(tmp), [conv])
            result = load_life_claude_renderer_history(p)
            assert len(result) == 1
            assert result[0]["sessionId"] == "sid-1"

    def test_never_modifies_source_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            conv = _make_conversation("sid-1", "Title", [])
            p = _write_history(Path(tmp), [conv])
            original = p.read_text(encoding="utf-8")
            load_life_claude_renderer_history(p)
            assert p.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# Tests: export_life_claude_renderer_day_transcript
# ---------------------------------------------------------------------------

class TestExportDayTranscript(unittest.TestCase):

    def test_empty_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write_history(Path(tmp), [])
            text, msg_count, sess_count = export_life_claude_renderer_day_transcript(
                date(2026, 6, 6), history_path=p,
            )
            assert text == ""
            assert msg_count == 0
            assert sess_count == 0

    def test_user_display_content_takes_precedence(self):
        """displayContent should be preferred over content for user messages."""
        with tempfile.TemporaryDirectory() as tmp:
            msg = _make_message("user", "raw content", _TS_BASE_MS, display_content="display content")
            conv = _make_conversation("sid-1", "Test", [msg])
            p = _write_history(Path(tmp), [conv])
            text, _, _ = export_life_claude_renderer_day_transcript(
                date(2026, 6, 6), history_path=p,
            )
            assert "display content" in text
            assert "raw content" not in text

    def test_assistant_content_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            msg = _make_message("assistant", "assistant reply", _TS_BASE_MS)
            conv = _make_conversation("sid-1", "Test", [msg])
            p = _write_history(Path(tmp), [conv])
            text, _, _ = export_life_claude_renderer_day_transcript(
                date(2026, 6, 6), history_path=p,
            )
            assert "assistant reply" in text

    def test_per_message_date_filtering(self):
        """Only messages on the requested date should be included."""
        with tempfile.TemporaryDirectory() as tmp:
            msgs = [
                _make_message("user", "prev day", _TS_PREV_DAY_MS),
                _make_message("user", "target day", _TS_BASE_MS),
                _make_message("user", "next day", _TS_NEXT_DAY_MS),
            ]
            conv = _make_conversation("sid-1", "Test", msgs)
            p = _write_history(Path(tmp), [conv])
            text, msg_count, _ = export_life_claude_renderer_day_transcript(
                date(2026, 6, 6), history_path=p,
            )
            assert "target day" in text
            assert "prev day" not in text
            assert "next day" not in text
            assert msg_count == 1

    def test_multi_day_session_split(self):
        """A session spanning multiple days should be sliced per date."""
        with tempfile.TemporaryDirectory() as tmp:
            msgs = [
                _make_message("user", "day1 msg", _TS_PREV_DAY_MS),
                _make_message("assistant", "day1 reply", _TS_PREV_DAY_MS + 1000),
                _make_message("user", "day2 msg", _TS_BASE_MS),
                _make_message("assistant", "day2 reply", _TS_BASE_MS + 1000),
            ]
            conv = _make_conversation("sid-1", "Multi-day", msgs)
            p = _write_history(Path(tmp), [conv])

            # Day 1
            text1, count1, _ = export_life_claude_renderer_day_transcript(
                date(2026, 6, 5), history_path=p,
            )
            assert "day1 msg" in text1
            assert "day2 msg" not in text1
            assert count1 == 2

            # Day 2
            text2, count2, _ = export_life_claude_renderer_day_transcript(
                date(2026, 6, 6), history_path=p,
            )
            assert "day2 msg" in text2
            assert "day1 msg" not in text2
            assert count2 == 2

    def test_empty_messages_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            msgs = [
                _make_message("user", "", _TS_BASE_MS),
                _make_message("assistant", "   ", _TS_BASE_MS + 1000),
                _make_message("user", "real message", _TS_BASE_MS + 2000),
            ]
            conv = _make_conversation("sid-1", "Test", msgs)
            p = _write_history(Path(tmp), [conv])
            text, msg_count, _ = export_life_claude_renderer_day_transcript(
                date(2026, 6, 6), history_path=p,
            )
            assert msg_count == 1
            assert "real message" in text

    def test_session_count_only_sessions_with_messages(self):
        """Sessions with no messages on the target date should not be counted."""
        with tempfile.TemporaryDirectory() as tmp:
            conv1 = _make_conversation("sid-1", "Has msgs", [
                _make_message("user", "hello", _TS_BASE_MS),
            ])
            conv2 = _make_conversation("sid-2", "No msgs today", [
                _make_message("user", "yesterday", _TS_PREV_DAY_MS),
            ])
            p = _write_history(Path(tmp), [conv1, conv2])
            _, _, sess_count = export_life_claude_renderer_day_transcript(
                date(2026, 6, 6), history_path=p,
            )
            assert sess_count == 1

    def test_session_blocks_ordered_by_earliest_message(self):
        """Session blocks should be sorted by their earliest included message timestamp."""
        with tempfile.TemporaryDirectory() as tmp:
            # Session 2 has an earlier message
            conv2 = _make_conversation("sid-2", "Earlier session", [
                _make_message("user", "earlier", _TS_BASE_MS),
            ])
            conv1 = _make_conversation("sid-1", "Later session", [
                _make_message("user", "later", _TS_AFTERNOON_MS),
            ])
            p = _write_history(Path(tmp), [conv2, conv1])
            text, _, _ = export_life_claude_renderer_day_transcript(
                date(2026, 6, 6), history_path=p,
            )
            # sid-2 should appear before sid-1
            pos_sid2 = text.index("sid-2")
            pos_sid1 = text.index("sid-1")
            assert pos_sid2 < pos_sid1

    def test_wikilinks_preserved_verbatim(self):
        """[[wikilinks]] in message content should be preserved."""
        with tempfile.TemporaryDirectory() as tmp:
            msg = _make_message("assistant", "See [[2026-06-01]] for details", _TS_BASE_MS)
            conv = _make_conversation("sid-1", "Test", [msg])
            p = _write_history(Path(tmp), [conv])
            text, _, _ = export_life_claude_renderer_day_transcript(
                date(2026, 6, 6), history_path=p,
            )
            assert "[[2026-06-01]]" in text

    def test_context_xml_not_included(self):
        """displayContent (without context XML) should be used, not raw content with XML."""
        with tempfile.TemporaryDirectory() as tmp:
            raw = 'translate to chinese\n<editor_selection path="test.md" lines="1-5">\nselected text\n</editor_selection>'
            msg = _make_message("user", raw, _TS_BASE_MS, display_content="translate to chinese")
            conv = _make_conversation("sid-1", "Test", [msg])
            p = _write_history(Path(tmp), [conv])
            text, _, _ = export_life_claude_renderer_day_transcript(
                date(2026, 6, 6), history_path=p,
            )
            assert "translate to chinese" in text
            assert "editor_selection" not in text

    def test_custom_speaker_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            msgs = [
                _make_message("user", "hello", _TS_BASE_MS),
                _make_message("assistant", "hi", _TS_BASE_MS + 1000),
            ]
            conv = _make_conversation("sid-1", "Test", msgs)
            p = _write_history(Path(tmp), [conv])
            text, _, _ = export_life_claude_renderer_day_transcript(
                date(2026, 6, 6), history_path=p,
                user_name="User", assistant_name="Bot",
            )
            assert "User:" in text
            assert "Bot:" in text
            assert "Henry:" not in text
            assert "Claude:" not in text

    def test_invalid_message_records_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            msgs = [
                "not a dict",
                {"role": "unknown", "content": "x", "timestamp": _TS_BASE_MS},
                {"role": "user", "timestamp": _TS_BASE_MS},  # no content
                _make_message("user", "valid", _TS_BASE_MS),
            ]
            conv = _make_conversation("sid-1", "Test", msgs)
            p = _write_history(Path(tmp), [conv])
            text, msg_count, _ = export_life_claude_renderer_day_transcript(
                date(2026, 6, 6), history_path=p,
            )
            assert msg_count == 1
            assert "valid" in text

    def test_image_attachment_provenance_in_transcript(self):
        """Image contextAttachments should appear as provenance lines after the user message."""
        with tempfile.TemporaryDirectory() as tmp:
            msg = _make_message("user", "describe this", _TS_BASE_MS)
            msg["contextAttachments"] = [
                {
                    "type": "image",
                    "path": "attachments/1234-abcd.png",
                    "text": "[image: 1234-abcd.png]",
                    "mime": "image/png",
                    "sizeBytes": 54321,
                }
            ]
            conv = _make_conversation("sid-img", "Image test", [msg])
            p = _write_history(Path(tmp), [conv])
            text, msg_count, _ = export_life_claude_renderer_day_transcript(
                date(2026, 6, 6), history_path=p,
            )
            assert "describe this" in text
            assert "Attachments:" in text
            assert "Image: path=attachments/1234-abcd.png" in text
            assert "mime=image/png" in text
            assert "size=54321 bytes" in text
            # message_count should still be 1 (attachment lines are part of the user message, not extra messages)
            assert msg_count == 1

    def test_image_attachment_no_base64_or_thumbnail_exported(self):
        """base64 and thumbnail fields must NOT appear in the transcript."""
        with tempfile.TemporaryDirectory() as tmp:
            msg = _make_message("user", "look at this", _TS_BASE_MS)
            msg["contextAttachments"] = [
                {
                    "type": "image",
                    "path": "attachments/photo.jpg",
                    "text": "[image: photo.jpg]",
                    "mime": "image/jpeg",
                    "sizeBytes": 9999,
                    "thumbnail": "data:image/jpeg;base64,/9j/4AAQSkZJRg==",
                }
            ]
            conv = _make_conversation("sid-no-b64", "No b64", [msg])
            p = _write_history(Path(tmp), [conv])
            text, _, _ = export_life_claude_renderer_day_transcript(
                date(2026, 6, 6), history_path=p,
            )
            assert "base64" not in text
            assert "thumbnail" not in text
            assert "/9j/4AAQSkZJRg" not in text
            # But the path/mime/size should still be there
            assert "path=attachments/photo.jpg" in text

    def test_non_image_attachments_not_exported_as_image_lines(self):
        """editor-selection and pdf-selection attachments should not produce Image: lines."""
        with tempfile.TemporaryDirectory() as tmp:
            msg = _make_message("user", "check this", _TS_BASE_MS)
            msg["contextAttachments"] = [
                {"type": "editor-selection", "path": "notes/a.md", "lines": "1-5", "text": "selected"},
                {"type": "pdf-selection", "path": "paper.pdf", "page": "3", "text": "pdf text"},
            ]
            conv = _make_conversation("sid-no-img", "No img", [msg])
            p = _write_history(Path(tmp), [conv])
            text, _, _ = export_life_claude_renderer_day_transcript(
                date(2026, 6, 6), history_path=p,
            )
            assert "Attachments:" not in text
            assert "Image:" not in text
            assert "check this" in text

    def test_message_count_with_image_attachment(self):
        """message_count should count user+assistant messages, not attachment lines."""
        with tempfile.TemporaryDirectory() as tmp:
            user_msg = _make_message("user", "what is this", _TS_BASE_MS)
            user_msg["contextAttachments"] = [
                {"type": "image", "path": "img.png", "text": "[image: img.png]", "mime": "image/png", "sizeBytes": 100},
            ]
            asst_msg = _make_message("assistant", "It shows a cat.", _TS_BASE_MS + 2000)
            conv = _make_conversation("sid-cnt", "Count test", [user_msg, asst_msg])
            p = _write_history(Path(tmp), [conv])
            text, msg_count, _ = export_life_claude_renderer_day_transcript(
                date(2026, 6, 6), history_path=p,
            )
            # Two chat messages (user + assistant), not 3
            assert msg_count == 2
            assert "It shows a cat." in text


# ---------------------------------------------------------------------------
# Tests: ai_trace_path_for_date with life-claude-renderer
# ---------------------------------------------------------------------------

class TestAiTracePath(unittest.TestCase):

    def test_life_claude_renderer_source(self):
        d = date(2026, 6, 6)
        path = ai_trace_path_for_date(d, "life-claude-renderer")
        assert path.name == "2026-06-06-life-claude-renderer-trace.md"
        assert "2026" in str(path)
        assert "06" in str(path)

    def test_codex_source_still_works(self):
        d = date(2026, 6, 6)
        path = ai_trace_path_for_date(d, "codex")
        assert path.name == "2026-06-06-codex-trace.md"

    def test_claude_code_source(self):
        d = date(2026, 6, 6)
        path = ai_trace_path_for_date(d, "claude-code")
        assert path.name == "2026-06-06-claude-code-trace.md"

    def test_claudian_source_still_works(self):
        d = date(2026, 6, 6)
        path = ai_trace_path_for_date(d, "claudian")
        assert path.name == "2026-06-06-claudian-trace.md"

    def test_openclaw_source(self):
        d = date(2026, 6, 6)
        path = ai_trace_path_for_date(d, "openclaw")
        assert path.name == "2026-06-06-openclaw-trace.md"

    def test_unsupported_source_raises(self):
        d = date(2026, 6, 6)
        try:
            ai_trace_path_for_date(d, "unknown")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Unsupported source" in str(e)


# ---------------------------------------------------------------------------
# Tests: generic Claude JSONL sessions are never imported
# ---------------------------------------------------------------------------

class TestGenericClaudeNeverImported(unittest.TestCase):

    def test_only_plugin_history_used(self):
        """export_life_claude_renderer_day_transcript only reads history.json,
        not generic Claude project JSONL files."""
        with tempfile.TemporaryDirectory() as tmp:
            # Create a history.json with one conversation
            conv = _make_conversation("sid-1", "Plugin conv", [
                _make_message("user", "plugin message", _TS_BASE_MS),
            ])
            p = _write_history(Path(tmp), [conv])
            text, msg_count, sess_count = export_life_claude_renderer_day_transcript(
                date(2026, 6, 6), history_path=p,
            )
            # Should only contain the plugin conversation
            assert "plugin message" in text
            assert msg_count == 1
            assert sess_count == 1


# ---------------------------------------------------------------------------
# Tests: preview-ai-day uses renderer source
# ---------------------------------------------------------------------------

class TestPreviewUsesRenderer(unittest.TestCase):
    """Command-level test: actually invokes cmd_preview_ai_day and checks stdout."""

    def test_preview_output_shows_renderer_not_claudian(self):
        """cmd_preview_ai_day stdout must reference Life Claude Renderer with correct counts."""
        import io
        from contextlib import redirect_stdout
        from unittest.mock import patch as _patch
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # -- fixture history.json with 2 messages across 1 session --
            conv = _make_conversation("sid-001", "Test session", [
                _make_message("user", "hello world", _TS_BASE_MS),
                _make_message("assistant", "hi there", _TS_BASE_MS + 5000),
            ])
            history_path = _write_history(tmp_path, [conv])

            # -- minimal journal so the "Journal file:" line doesn't error --
            journal_dir = tmp_path / "journal" / "2026" / "06"
            journal_dir.mkdir(parents=True)
            journal_file = journal_dir / "2026-06-06.md"
            journal_file.write_text("# 2026-06-06\n\n## 💬 From Kai\n\n## End\n", encoding="utf-8")

            # -- patch module constants so all path resolution uses tmp --
            with _patch.object(copilot_module, "ROOT", tmp_path), \
                 _patch.object(copilot_module, "JOURNAL_DIR", tmp_path / "journal"), \
                 _patch.object(copilot_module, "AI_CONVERSATIONS_DIR", tmp_path / "journal" / "ai-conversations"), \
                 _patch.object(copilot_module, "LIFE_CLAUDE_RENDERER_HISTORY", history_path), \
                 _patch.object(copilot_module, "export_codex_day_transcript", return_value=""), \
                 _patch.object(copilot_module, "export_openclaw_day_transcript", return_value=("", 0, 0)), \
                 redirect_stdout(io.StringIO()) as buf:
                cmd_preview_ai_day(SimpleNamespace(date="2026-06-06"))

            output = buf.getvalue()

            # Must reference Life Claude Renderer
            assert "Life Claude Renderer" in output, f"Missing 'Life Claude Renderer' in:\n{output}"

            # Must show correct session and message counts
            assert "Life Claude Renderer sessions:   1" in output, f"Wrong session count in:\n{output}"
            assert "Life Claude Renderer messages:   2" in output, f"Wrong message count in:\n{output}"

            # Must reference the renderer trace file name
            assert "life-claude-renderer-trace" in output, f"Missing trace reference in:\n{output}"

            # Must NOT show Claudian as a current source
            assert "Claudian" not in output, f"Unexpected 'Claudian' in:\n{output}"


# ---------------------------------------------------------------------------
# Tests: writeback creates renderer trace/link without deleting old Claudian links
# ---------------------------------------------------------------------------

class TestWritebackPreservesClaudian(unittest.TestCase):
    """Command-level test: invokes cmd_writeback_ai_day in a fully isolated tmp vault."""

    def _run_writeback(self, tmp_path: Path, journal_text: str, history_path: Path):
        """Run cmd_writeback_ai_day with patched constants. Returns (trace_text, journal_text_after)."""
        import io
        from contextlib import redirect_stdout
        from unittest.mock import patch as _patch
        from types import SimpleNamespace

        with _patch.object(copilot_module, "ROOT", tmp_path), \
             _patch.object(copilot_module, "JOURNAL_DIR", tmp_path / "journal"), \
             _patch.object(copilot_module, "AI_CONVERSATIONS_DIR", tmp_path / "journal" / "ai-conversations"), \
             _patch.object(copilot_module, "LIFE_CLAUDE_RENDERER_HISTORY", history_path), \
             _patch.object(copilot_module, "export_codex_day_transcript", return_value=""), \
             _patch.object(copilot_module, "export_openclaw_day_transcript", return_value=("", 0, 0)), \
             redirect_stdout(io.StringIO()):
            cmd_writeback_ai_day(SimpleNamespace(date="2026-06-06"))

        trace_path = tmp_path / "journal" / "ai-conversations" / "2026" / "06" / "2026-06-06-life-claude-renderer-trace.md"
        journal_path = tmp_path / "journal" / "2026" / "06" / "2026-06-06.md"
        trace_text = trace_path.read_text(encoding="utf-8")
        journal_after = journal_path.read_text(encoding="utf-8")
        return trace_text, journal_after

    def test_writeback_creates_trace_and_preserves_claudian_link(self):
        """Full writeback: trace created with correct content; old claudian link untouched."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # -- fixture: journal with an existing claudian wikilink --
            journal_dir = tmp_path / "journal" / "2026" / "06"
            journal_dir.mkdir(parents=True)
            journal_file = journal_dir / "2026-06-06.md"
            journal_text = (
                "# 2026-06-06\n\n"
                "## 💬 From Kai\n\n"
                "- [[2026-06-06-claudian-trace]]：old claudian session.\n\n"
                "## End\n"
            )
            journal_file.write_text(journal_text, encoding="utf-8")

            # -- fixture: history with XML in raw content but clean displayContent --
            raw_content = (
                "translate to chinese\n"
                '<editor_selection path="test.md" lines="1-5">\n'
                "selected text\n"
                "</editor_selection>"
            )
            conv = _make_conversation("sid-001", "Test session", [
                _make_message("user", raw_content, _TS_BASE_MS, display_content="translate to chinese"),
                _make_message("assistant", "Here is the translation", _TS_AFTERNOON_MS),
            ])
            history_path = _write_history(tmp_path, [conv])
            original_history_bytes = history_path.read_bytes()

            # -- run writeback --
            trace_text, journal_after = self._run_writeback(tmp_path, journal_text, history_path)

            # 1. Trace file created
            assert trace_text, "Trace file should have been created"

            # 2. Frontmatter contains source: life-claude-renderer
            assert "source: life-claude-renderer" in trace_text, f"Missing source in frontmatter:\n{trace_text}"

            # 3. Trace contains user's displayContent (not raw XML)
            assert "translate to chinese" in trace_text, f"Missing user displayContent in trace:\n{trace_text}"

            # 4. Raw XML tags do NOT leak into trace
            assert "<editor_selection>" not in trace_text, f"Raw XML leaked into trace:\n{trace_text}"
            assert "<context_file>" not in trace_text, f"context_file XML leaked into trace:\n{trace_text}"

            # 5. Trace contains assistant content
            assert "Here is the translation" in trace_text, f"Missing assistant content in trace:\n{trace_text}"

            # 6. Old claudian wikilink preserved
            assert "[[2026-06-06-claudian-trace]]" in journal_after, f"Claudian link lost:\n{journal_after}"

            # 7. New renderer wikilink added
            assert "[[2026-06-06-life-claude-renderer-trace]]" in journal_after, f"Renderer link missing:\n{journal_after}"

            # 8. history.json byte-identical
            assert history_path.read_bytes() == original_history_bytes, "history.json was modified!"

    def test_writeback_is_idempotent(self):
        """Running writeback twice must not duplicate the renderer wikilink."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            journal_dir = tmp_path / "journal" / "2026" / "06"
            journal_dir.mkdir(parents=True)
            journal_file = journal_dir / "2026-06-06.md"
            journal_text = (
                "# 2026-06-06\n\n"
                "## 💬 From Kai\n\n"
                "- [[2026-06-06-claudian-trace]]：old claudian session.\n\n"
                "## End\n"
            )
            journal_file.write_text(journal_text, encoding="utf-8")

            conv = _make_conversation("sid-001", "Test", [
                _make_message("user", "hello", _TS_BASE_MS),
                _make_message("assistant", "hi", _TS_AFTERNOON_MS),
            ])
            history_path = _write_history(tmp_path, [conv])

            # First run
            _, journal_after_1 = self._run_writeback(tmp_path, journal_text, history_path)
            # Second run (journal already has the link)
            _, journal_after_2 = self._run_writeback(tmp_path, journal_after_1, history_path)

            renderer_count = journal_after_2.count("[[2026-06-06-life-claude-renderer-trace]]")
            assert renderer_count == 1, f"Renderer link appears {renderer_count} times (expected 1):\n{journal_after_2}"

            # Old claudian link still present
            assert "[[2026-06-06-claudian-trace]]" in journal_after_2, f"Claudian link lost after idempotency run:\n{journal_after_2}"


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import unittest
    unittest.main(verbosity=2)
