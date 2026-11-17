"""Tests for the daily source registry (docs/rfcs/source-registry-rfc.md)."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import copilot

DAY = date(2026, 8, 13)
SESSIONS = {
    spec.name: spec.name.split("-")[0] + "1111"
    for spec in copilot.SOURCES
}
EXPECTED_ORDER = [
    "codex",
    "life-claude-renderer",
    "claude-code",
    "antigravity",
    "deepseek-harness",
    "openclaw",
    "zshs-codex",
    "zshs-claude-code",
    "zshs-catpaw",
    "claude-web",
    "chatgpt-web",
    "deepseek-web",
    "gemini-web",
]
TIMELINE_LABELS = {
    "codex": "Codex",
    "life-claude-renderer": "Life Claude Renderer",
    "claude-code": "Claude Code",
    "antigravity": "Antigravity",
    "deepseek-harness": "DeepSeek Harness",
    "openclaw": "Kai / Telegram",
    "zshs-codex": "zshs Codex",
    "zshs-claude-code": "zshs Claude Code",
    "zshs-catpaw": "zshs CatPaw",
    "claude-web": "Claude Web",
    "chatgpt-web": "ChatGPT Web",
    "deepseek-web": "DeepSeek Web",
    "gemini-web": "Gemini Web",
}


def _msg(hour: int, speaker: str, text: str) -> str:
    stamp = datetime(2026, 8, 13, hour, 0).astimezone().isoformat()
    return f"[{copilot.format_chat_timestamp(stamp)}] {speaker}: {text}"


def _transcripts() -> dict[str, str]:
    texts: dict[str, str] = {}
    for index, spec in enumerate(copilot.SOURCES):
        hour = 9 + index
        texts[spec.name] = (
            f"### {spec.heading} {SESSIONS[spec.name]}\n\n"
            f"{_msg(hour, 'Henry', spec.preview_label + ' question')}\n\n"
            f"{_msg(hour, spec.assistant, spec.preview_label + ' answer')}\n"
        )
    return texts


class SourceRegistryTest(unittest.TestCase):
    def test_registry_order_labels_and_policy(self) -> None:
        self.assertEqual([spec.name for spec in copilot.SOURCES], EXPECTED_ORDER)
        for spec in copilot.SOURCES:
            self.assertTrue(spec.assistant, spec.name)
            self.assertTrue(spec.heading, spec.name)
            self.assertTrue(spec.trace_title, spec.name)
            self.assertTrue(spec.from_kai_description, spec.name)
            self.assertIsNotNone(spec.pull, spec.name)
        self.assertEqual(
            [spec.name for spec in copilot.ZSHS_SOURCE_SPECS],
            ["zshs-codex", "zshs-claude-code", "zshs-catpaw"],
        )
        self.assertEqual(
            [spec.name for spec in copilot.WEB_SOURCE_SPECS],
            ["claude-web", "chatgpt-web", "deepseek-web", "gemini-web"],
        )
        self.assertTrue(copilot.SOURCE_BY_NAME["openclaw"].required)
        self.assertTrue(copilot.SOURCE_BY_NAME["chatgpt-web"].required)
        for name in ("claude-web", "deepseek-web", "gemini-web"):
            self.assertFalse(copilot.SOURCE_BY_NAME[name].required, name)
        for spec in copilot.ZSHS_SOURCE_SPECS:
            self.assertEqual(spec.group, "zshs")
            self.assertFalse(spec.required)
            self.assertEqual(spec.frontmatter, ("host: zshs",))
        self.assertIn("zshs", copilot.GROUP_PULLS)

    def test_pull_reads_source_records_only_when_asked(self) -> None:
        with patch.object(copilot, "export_codex_day_transcript", return_value="body"), \
                patch.object(
                    copilot, "codex_day_source_records",
                    side_effect=AssertionError("records must stay lazy"),
                ):
            result = copilot.pull_codex(DAY)
            self.assertEqual((result.status, result.transcript), ("pulled", "body"))
        with patch.object(copilot, "codex_day_source_records", return_value=[("s", "t", "user", "u")]):
            self.assertEqual(result.load_records(), [("s", "t", "user", "u")])

    def test_zshs_group_is_skipped_without_the_flag_and_optional_on_failure(self) -> None:
        options = copilot.SourceOptions(pull_zshs=False)
        group = copilot.pull_zshs_group(DAY, options)
        self.assertEqual(group.status, "skipped")
        self.assertEqual(set(group.results), {"zshs-codex", "zshs-claude-code", "zshs-catpaw"})
        with patch.object(copilot, "zshs_sync_day", side_effect=copilot.ZshsImportUnavailable("offline")), \
                redirect_stdout(io.StringIO()):
            group = copilot.pull_zshs_group(DAY, copilot.SourceOptions(pull_zshs=True))
        self.assertEqual(group.status, "unavailable")
        self.assertEqual(group.detail, "offline")
        self.assertEqual({result.status for result in group.results.values()}, {"unavailable"})


class WritebackGoldenTest(unittest.TestCase):
    """One deterministic session per source: exact trace bytes and From Kai order."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.journal = self.root / "journal" / "2026" / "08" / "2026-08-13.md"
        self.journal.parent.mkdir(parents=True)
        self.journal.write_text("# 2026-08-13\n\n## 💬 From Kai\n", encoding="utf-8")
        self.transcripts = _transcripts()
        harness = copilot.SourceResult(
            "pulled", self.transcripts["deepseek-harness"], message_count=2, session_count=1
        )
        self.patchers = [
            patch.object(copilot, "SOURCES", tuple(
                replace(spec, pull=lambda _day, _options: harness)
                if spec.name == "deepseek-harness" else spec for spec in copilot.SOURCES
            )),
            patch.object(copilot, "ROOT", self.root),
            patch.object(copilot, "JOURNAL_DIR", self.root / "journal"),
            patch.object(copilot, "AI_CONVERSATIONS_DIR", self.root / "journal" / "ai-conversations"),
            patch.object(copilot, "export_codex_day_transcript",
                         return_value=self.transcripts["codex"]),
            patch.object(copilot, "export_life_claude_renderer_day_transcript",
                         return_value=(self.transcripts["life-claude-renderer"], 2, 1)),
            patch.object(copilot, "export_claude_code_day_transcript",
                         return_value=(self.transcripts["claude-code"], 2, 1)),
            patch.object(copilot, "export_antigravity_day_transcript",
                         return_value=(self.transcripts["antigravity"], 2, 1)),
            patch.object(copilot, "export_openclaw_day_transcript",
                         return_value=(self.transcripts["openclaw"], 2, 1)),
            patch.object(copilot, "zshs_sync_day", return_value={"status": "pulled"}),
            patch.object(copilot, "export_zshs_codex_day_transcript",
                         return_value=self.transcripts["zshs-codex"]),
            patch.object(copilot, "export_zshs_claude_code_day_transcript",
                         return_value=(self.transcripts["zshs-claude-code"], 2, 1)),
            patch.object(copilot, "export_zshs_catpaw_day_transcript",
                         return_value=(self.transcripts["zshs-catpaw"], 2, 1)),
            patch.object(copilot, "export_web_chat_day_transcript",
                         side_effect=lambda provider, target: (
                             self.transcripts[copilot.WEB_CHAT_SOURCES[provider][0]], 2, 1)),
            patch.object(copilot, "refresh_web_chats_for_writeback"),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def test_traces_match_the_registry_golden_byte_for_byte(self) -> None:
        with redirect_stdout(io.StringIO()):
            result = copilot.writeback_ai_day(DAY, web_chats=True, pull_zshs=True)
        for spec in copilot.SOURCES:
            expected = "\n".join([
                "---",
                f"date: {DAY.isoformat()}",
                f"source: {spec.name}",
                *spec.frontmatter,
                "generated_by: scripts/copilot.py writeback-ai-day",
                "---",
                "",
                f"# {DAY.isoformat()} {spec.trace_title}",
                "",
                # Codex is the one pull that strips, as writeback always did.
                self.transcripts[spec.name].strip()
                if spec.name == "codex" else self.transcripts[spec.name],
            ])
            path = self.root / "journal" / "ai-conversations" / "2026" / "08" / (
                f"{DAY.isoformat()}-{spec.name}-trace.md"
            )
            self.assertEqual(path.read_text(encoding="utf-8"), expected, spec.name)
            self.assertIsInstance(result[spec.name], copilot.SourceResult)
            self.assertEqual(result[spec.name].status, "pulled")
        self.assertEqual(result["zshs_status"], "pulled")
        self.assertEqual(result["openclaw_status"], "pulled")

    def test_from_kai_bullets_follow_registry_order_once_each(self) -> None:
        with redirect_stdout(io.StringIO()):
            copilot.writeback_ai_day(DAY, web_chats=True, pull_zshs=True)
        from_kai = self.journal.read_text(encoding="utf-8").split("## 💬 From Kai", 1)[1]
        bullets = [
            line for line in from_kai.splitlines()
            if line.startswith("- [[")
        ]
        self.assertEqual(bullets, [
            f"- [[{DAY.isoformat()}-{spec.name}-trace]]：{spec.from_kai_description}"
            for spec in copilot.SOURCES
        ])

    def test_timeline_names_every_session_in_registry_order(self) -> None:
        with redirect_stdout(io.StringIO()):
            copilot.writeback_ai_day(DAY, web_chats=True, pull_zshs=True)
        text = copilot.day_timeline_path(DAY).read_text(encoding="utf-8")
        positions = []
        for index, spec in enumerate(copilot.SOURCES):
            hour = 9 + index
            needle = (
                f"- {hour:02d}:00 · {TIMELINE_LABELS[spec.name]} "
                f"{SESSIONS[spec.name][:8]} · Henry 1, AI 1 · "
            )
            self.assertIn(needle, text, spec.name)
            positions.append(text.index(needle))
        self.assertEqual(positions, sorted(positions))


class PreviewZshsTest(unittest.TestCase):
    """preview-ai-day used to lack zshs entirely; it now reads the cache only."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.journal = self.root / "journal" / "2026" / "08" / "2026-08-13.md"
        self.journal.parent.mkdir(parents=True)
        self.journal.write_text("# 2026-08-13\n\n## 💬 From Kai\n", encoding="utf-8")
        self.patchers = [
            patch.object(copilot, "ROOT", self.root),
            patch.object(copilot, "JOURNAL_DIR", self.root / "journal"),
            patch.object(copilot, "AI_CONVERSATIONS_DIR", self.root / "journal" / "ai-conversations"),
            patch.object(copilot, "export_codex_day_transcript", return_value=""),
            patch.object(copilot, "export_life_claude_renderer_day_transcript", return_value=("", 0, 0)),
            patch.object(copilot, "export_claude_code_day_transcript", return_value=("", 0, 0)),
            patch.object(copilot, "export_antigravity_day_transcript", return_value=("", 0, 0)),
            patch.object(copilot, "export_openclaw_day_transcript", return_value=("", 0, 0)),
            patch.object(copilot, "zshs_sync_day", side_effect=AssertionError("preview must not open SSH")),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def _cache_zshs_trace(self) -> Path:
        path = copilot.ai_trace_path_for_date(DAY, "zshs-codex")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\ndate: 2026-08-13\nsource: zshs-codex\nhost: zshs\n---\n\n"
            "# 2026-08-13 zshs Codex Trace\n\n"
            f"### zshs Codex Thread {SESSIONS['zshs-codex']}\n\n"
            f"{_msg(9, 'Henry', '工位上的问题')}\n\n"
            f"{_msg(9, 'Codex', '工位上的回答')}\n",
            encoding="utf-8",
        )
        return path

    def test_preview_reports_cached_and_missing_zshs(self) -> None:
        path = self._cache_zshs_trace()
        out = io.StringIO()
        with redirect_stdout(out):
            copilot.cmd_preview_ai_day(SimpleNamespace(date=DAY.isoformat(), web_chats=False))
        text = out.getvalue()
        relative = path.relative_to(self.root)
        self.assertIn(f"  zshs Codex trace file:           {relative} (cached, ", text)
        self.assertIn("  zshs Codex sessions:             1", text)
        self.assertIn("  zshs Codex messages:             2", text)
        self.assertIn("  zshs Claude Code:                (not cached for this date)", text)
        self.assertIn("  zshs CatPaw:                     (not cached for this date)", text)
        self.assertIn("Codex conversations on the internship host (zshs).", text)
        self.assertNotIn("No AI conversations found", text)


if __name__ == "__main__":
    unittest.main()


class RequiredOptionalMatrixTest(unittest.TestCase):
    """Required/optional policy is data on the spec, not prose in the pull path."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.journal = self.root / "journal" / "2026" / "08" / "2026-08-13.md"
        self.journal.parent.mkdir(parents=True)
        self.journal.write_text("# 2026-08-13\n\n## 💬 From Kai\n", encoding="utf-8")
        self.patchers = [
            patch.object(copilot, "ROOT", self.root),
            patch.object(copilot, "JOURNAL_DIR", self.root / "journal"),
            patch.object(copilot, "AI_CONVERSATIONS_DIR", self.root / "journal" / "ai-conversations"),
            patch.object(copilot, "export_codex_day_transcript",
                         return_value="### Codex Thread c1\n\n[8/13/26 9:00 AM] Henry: hi\n"),
            patch.object(copilot, "export_life_claude_renderer_day_transcript", return_value=("", 0, 0)),
            patch.object(copilot, "export_claude_code_day_transcript", return_value=("", 0, 0)),
            patch.object(copilot, "export_antigravity_day_transcript", return_value=("", 0, 0)),
            patch.object(copilot, "zshs_sync_day", return_value={"status": "empty"}),
            patch.object(copilot, "export_zshs_codex_day_transcript", return_value=""),
            patch.object(copilot, "export_zshs_claude_code_day_transcript", return_value=("", 0, 0)),
            patch.object(copilot, "export_zshs_catpaw_day_transcript", return_value=("", 0, 0)),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def test_openclaw_blocks_unless_the_flag_is_given(self) -> None:
        with patch.object(copilot, "export_openclaw_day_transcript",
                          side_effect=copilot.OpenClawImportUnavailable("offline")), \
                self.assertRaisesRegex(copilot.OpenClawImportUnavailable, "no partial writeback"):
            with redirect_stdout(io.StringIO()):
                copilot.writeback_ai_day(DAY)
        output = io.StringIO()
        with patch.object(copilot, "export_openclaw_day_transcript",
                          side_effect=copilot.OpenClawImportUnavailable("offline")), \
                redirect_stdout(output):
            result = copilot.writeback_ai_day(DAY, allow_missing_openclaw=True)
        self.assertEqual(result["openclaw"].status, "unavailable")
        self.assertIn("--allow-missing-openclaw was set", output.getvalue())

    def test_zshs_is_optional_and_passes_the_cooldown_flag(self) -> None:
        with patch.object(copilot, "zshs_sync_day",
                          side_effect=copilot.ZshsImportUnavailable("offline")) as sync, \
                redirect_stdout(io.StringIO()):
            result = copilot.writeback_ai_day(
                DAY, pull_zshs=True, zshs_respect_cooldown=False
            )
        sync.assert_called_once_with(DAY, respect_cooldown=False)
        self.assertEqual(result["zshs_status"], "unavailable")
        self.assertEqual(result["zshs_detail"], "offline")
        self.assertEqual(result["zshs-codex"].status, "unavailable")

    def test_chatgpt_web_is_required_while_the_other_web_sources_are_optional(self) -> None:
        required = {spec.name for spec in copilot.SOURCES if spec.required}
        self.assertEqual(required, {"openclaw", "chatgpt-web"})
        self.assertEqual(
            {spec.missing_flag for spec in copilot.SOURCES if spec.required},
            {"--allow-missing-openclaw", "--allow-missing-web-chats"},
        )
        for name in ("claude-web", "deepseek-web", "gemini-web"):
            self.assertFalse(copilot.SOURCE_BY_NAME[name].required, name)
            self.assertEqual(
                copilot.SOURCE_BY_NAME[name].missing_flag, "--allow-missing-web-chats"
            )
        # WeChat has its own importer and is deliberately outside the registry.
        self.assertNotIn("wechat", {spec.name for spec in copilot.SOURCES})


class Stage2ResultTest(unittest.TestCase):
    """Results, not log substrings, carry the refresh status lines."""

    def _refresh(self, args_namespace) -> str:
        out = io.StringIO()
        with patch.object(copilot, "refresh_schedule_snapshot", return_value=False), \
                redirect_stdout(out):
            copilot.cmd_refresh_ai_day(args_namespace)
        return out.getvalue()

    def test_refresh_reads_openclaw_and_zshs_status_from_results(self) -> None:
        result = {
            "openclaw": copilot.SourceResult("unavailable"),
            "zshs_status": "empty",
        }
        with patch.object(copilot, "writeback_ai_day", return_value=result):
            output = self._refresh(SimpleNamespace(
                date=DAY.isoformat(), no_openclaw=False, no_zshs=False, verbose=False
            ))
        self.assertEqual(output.strip(), "zshs: empty\nopenclaw: unavailable")

    def test_no_conversations_exception_carries_the_statuses(self) -> None:
        failure = copilot.NoAIConversations(
            "No AI conversations",
            {"openclaw": copilot.SourceResult("unavailable")},
            {"zshs": copilot.SourceGroupResult("unavailable")},
        )
        with patch.object(copilot, "writeback_ai_day", side_effect=failure):
            output = self._refresh(SimpleNamespace(
                date=DAY.isoformat(), no_openclaw=False, no_zshs=False, verbose=False
            ))
        self.assertEqual(output.strip(), "zshs: unavailable\nopenclaw: unavailable")

    def test_finalize_output_stays_json_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            hook = Path(temp) / "hook.json"
            hook.write_text(json.dumps({"date": DAY.isoformat()}), encoding="utf-8")
            result = {
                "journal": "/vault/journal/day.md",
                "codex": copilot.SourceResult(
                    "pulled", transcript="body", trace_path=Path("/vault/trace.md")
                ),
            }
            out = io.StringIO()
            with patch.object(copilot, "writeback_ai_day", return_value=result), \
                    redirect_stdout(out):
                copilot.cmd_finalize_ai_day(
                    SimpleNamespace(hook_input_file=str(hook), date=None)
                )
            payload = json.loads(out.getvalue())
        self.assertEqual(payload["codex"]["status"], "pulled")
        self.assertEqual(payload["codex"]["transcript_chars"], 4)
        self.assertEqual(payload["codex"]["trace"], "/vault/trace.md")


class SharedTraceParserTest(unittest.TestCase):
    """The guard and the timeline read the same parser (stage 3)."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.trace_dir = self.root / "journal" / "ai-conversations" / "2026" / "08"
        self.trace_dir.mkdir(parents=True)
        self.patchers = [
            patch.object(copilot, "ROOT", self.root),
            patch.object(copilot, "JOURNAL_DIR", self.root / "journal"),
            patch.object(copilot, "AI_CONVERSATIONS_DIR", self.root / "journal" / "ai-conversations"),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def _text(self) -> str:
        return "\n".join([
            "---",
            "date: 2026-08-13",
            "source: chatgpt-web",
            "---",
            "",
            "# 2026-08-13 ChatGPT Web Trace",
            "",
            "### ChatGPT Web Conversation abc12345 [Health] - sleep data",
            "",
            "Source: <https://chatgpt.com/c/abc12345>",
            "",
            _msg(9, "Henry", "question"),
            "",
            _msg(9, "ChatGPT", "answer"),
            "",
            "### Codex Thread <id> - quoted inside the answer",
            "",
            "<!-- openclaw-manual-begin channel=telegram source=henry-paste -->",
            "### Kai / Telegram (supplied by Henry)",
            "",
            "[8/13/26 4:42 AM] Henry: pasted",
            "",
            "[8/13/26 4:43 AM] Kai: yes",
            "<!-- openclaw-manual-end -->",
            _msg(11, "Henry", "after the paste"),
        ]) + "\n"

    def test_sessions_keep_heading_metadata_and_manual_blocks(self) -> None:
        text = self._text()
        sessions = copilot.parse_trace(text, (copilot.TRACE_USER, *copilot.TIMELINE_ASSISTANTS))
        web = next(session for session in sessions if session.label == "ChatGPT Web")
        self.assertEqual(
            (web.session, web.title, web.tags), ("abc12345", "sleep data", " [Health]")
        )
        manual = next(session for session in sessions if session.manual)
        self.assertEqual((manual.label, manual.session), ("Kai", manual.heading))
        self.assertTrue(all(unit["manual"] for unit in manual.units if unit["kind"] == "message"))
        # A quoted heading is text, not a session, for both consumers now.
        self.assertNotIn("<id>", {session.session for session in sessions})
        # Units keep every line, so the trace can be rebuilt from them.
        self.assertEqual(
            "\n".join(unit for session in sessions for line in session.units for unit in line["lines"]),
            text,
        )

    def test_guard_and_timeline_use_the_one_parser(self) -> None:
        self.assertFalse(hasattr(copilot, "TIMELINE_SESSION_HEADING_RE"))
        path = self.trace_dir / "2026-08-13-chatgpt-web-trace.md"
        path.write_text(self._text(), encoding="utf-8")
        guard_units = copilot.split_trace_units(self._text(), "ChatGPT")
        self.assertEqual(
            guard_units,
            [
                unit
                for session in copilot.parse_trace(
                    self._text(), (copilot.TRACE_USER, "ChatGPT")
                )
                for unit in session.units
            ],
        )
        messages = copilot.day_timeline_messages(DAY)
        self.assertEqual(
            [message["label"] for message in messages],
            ["ChatGPT Web", "ChatGPT Web", "Kai", "Kai", "chatgpt-web"],
        )
        self.assertEqual(
            [message["text"] for message in messages],
            [
                "question\n",
                "answer\n\n### Codex Thread <id> - quoted inside the answer\n",
                "pasted\n",
                "yes",
                "after the paste\n",
            ],
        )
