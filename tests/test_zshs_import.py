"""Tests for the optional zshs (internship host) trace import."""

from __future__ import annotations

import base64
import io
import json
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import patch

from scripts import copilot

DAY = date(2026, 11, 17)
THREAD = "01a1e72b-f777-7251-a5af-eec7406b4c38"


def codex_rows() -> list:
    return [
        {
            "timestamp": "2026-11-17T01:43:00Z",
            "type": "session_meta",
            "payload": {"id": THREAD, "thread_source": "user"},
        },
        {
            "timestamp": "2026-11-17T01:43:00Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "工位上的问题"}],
            },
        },
        {
            "timestamp": "2026-11-17T01:44:00Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "工位上的回答"}],
            },
        },
    ]


def claude_rows() -> list:
    return [
        {
            "type": "user",
            "timestamp": "2026-11-17T02:00:00Z",
            "uuid": "u1",
            "message": {"content": "claude 的问题"},
        },
        {
            "type": "assistant",
            "timestamp": "2026-11-17T02:01:00Z",
            "uuid": "u2",
            "message": {"model": "x", "content": [{"type": "text", "text": "claude 的回答"}]},
        },
    ]


def catpaw_rows() -> list:
    return [
        {"session": "c1", "title": "研究", "ts": "2026-11-17T10:00:00+08:00", "role": "user", "text": "CatPaw 的问题"},
        {"session": "c1", "title": "研究", "ts": "2026-11-17T10:01:00+08:00", "role": "assistant", "text": "CatPaw 的回答"},
    ]


def write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


class ZshsCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.cache = Path(self.temp.name).resolve()
        self.patchers = [
            patch.object(copilot, "ZSHS_CACHE_DIR", self.cache),
            patch.object(copilot, "ZSHS_CODEX_CACHE_DIR", self.cache / "codex" / "sessions"),
            patch.object(copilot, "ZSHS_CLAUDE_CACHE_DIR", self.cache / "claude-code" / "projects"),
            patch.object(copilot, "ZSHS_CATPAW_CACHE_DIR", self.cache / "catpaw"),
            patch.object(copilot, "ZSHS_CATPAW_DB", "C:/Users/zshs9/catpaw.db"),
            patch.object(copilot, "ZSHS_UNREACHABLE_MARKER", self.cache / "last-unreachable"),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def write_codex(self) -> Path:
        path = copilot.ZSHS_CODEX_CACHE_DIR / "2026" / "11" / "17" / "rollout-2026-11-17T09-43-00.jsonl"
        write_jsonl(path, codex_rows())
        return path

    def test_codex_day_transcript_keeps_the_zshs_label_and_records(self) -> None:
        self.write_codex()
        text = copilot.export_zshs_codex_day_transcript(DAY)
        self.assertIn(f"### zshs Codex Thread {THREAD}", text)
        self.assertIn("[11/17/26 9:43 AM] Henry: 工位上的问题", text)
        self.assertIn("[11/17/26 9:44 AM] Codex: 工位上的回答", text)
        records = copilot.zshs_codex_day_source_records(DAY)
        self.assertEqual([record[2] for record in records], ["user", "assistant"])

    def test_claude_code_day_transcript_reuses_the_visible_message_rules(self) -> None:
        write_jsonl(
            copilot.ZSHS_CLAUDE_CACHE_DIR / "-Users-zshs9-internship" / "22222222-2222-4222-8222-222222222222.jsonl",
            claude_rows(),
        )
        text, messages, sessions = copilot.export_zshs_claude_code_day_transcript(DAY)
        self.assertEqual((messages, sessions), (2, 1))
        self.assertIn("### zshs Claude Code Session 22222222-2222-4222-8222-222222222222", text)
        self.assertIn("[11/17/26 10:00 AM] Henry: claude 的问题", text)
        records = copilot.zshs_claude_code_day_source_records(DAY)
        self.assertEqual([record[2] for record in records], ["user", "assistant"])

    def test_catpaw_day_transcript_and_records(self) -> None:
        write_jsonl(copilot.ZSHS_CATPAW_CACHE_DIR / "c1.jsonl", catpaw_rows())
        text, messages, sessions = copilot.export_zshs_catpaw_day_transcript(DAY)
        self.assertEqual((messages, sessions), (2, 1))
        self.assertIn("### zshs CatPaw Session c1 - 研究", text)
        self.assertIn("[11/17/26 10:00 AM] Henry: CatPaw 的问题", text)
        self.assertIn("[11/17/26 10:01 AM] CatPaw: CatPaw 的回答", text)
        records = copilot.zshs_catpaw_day_source_records(DAY)
        self.assertEqual([record[2] for record in records], ["user", "assistant"])

    def test_archive_refuses_parent_paths(self) -> None:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            info = tarfile.TarInfo("../escape.txt")
            payload = b"x"
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        with self.assertRaises(copilot.ZshsImportUnavailable):
            copilot.zshs_extract_archive(buffer.getvalue(), self.cache / "out")

    def test_sync_day_reports_pulled_and_clears_the_failure_marker(self) -> None:
        copilot.ZSHS_UNREACHABLE_MARKER.write_text("old", encoding="utf-8")
        with patch.object(copilot, "zshs_extract_range",
                          side_effect=lambda *a, **k: {"status": "pulled", "files": 1, "records": 2}):
            result = copilot.zshs_sync_day(DAY, respect_cooldown=False)
        self.assertEqual(result["status"], "pulled")
        self.assertFalse(copilot.ZSHS_UNREACHABLE_MARKER.exists())


    def test_extract_range_decodes_a_filtered_archive(self) -> None:
        row = {
            "timestamp": "2026-11-17T01:43:00Z",
            "type": "response_item",
            "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "来自过滤件"}]},
        }
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            data = (json.dumps(row, ensure_ascii=False) + chr(10)).encode("utf-8")
            info = tarfile.TarInfo("2026/11/17/rollout-x.jsonl")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        payload = base64.b64encode(buffer.getvalue()).decode("ascii")
        with patch.object(copilot, "zshs_python", return_value="KEPT 1 1" + chr(10) + payload):
            result = copilot.zshs_extract_range(DAY, DAY, "codex")
        self.assertEqual(result["files"], 1)
        self.assertEqual(result["records"], 1)
        text = copilot.export_zshs_codex_day_transcript(DAY)
        self.assertIn("来自过滤件", text)

    def test_unreachable_host_opens_a_cooldown_and_raises(self) -> None:
        failure = copilot.ZshsImportUnavailable("connect timed out")
        with patch.object(copilot, "zshs_extract_range", side_effect=failure):
            with self.assertRaises(copilot.ZshsImportUnavailable):
                copilot.zshs_sync_day(DAY, respect_cooldown=False)
        self.assertTrue(copilot.ZSHS_UNREACHABLE_MARKER.exists())
        with self.assertRaisesRegex(copilot.ZshsImportUnavailable, "recently"):
            copilot.zshs_sync_day(DAY)


class ZshsWritebackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.journal = self.root / "journal" / "2026" / "11" / "2026-11-17.md"
        self.journal.parent.mkdir(parents=True)
        self.journal.write_text(
            "# 2026-11-17\n\n## 💬 From Kai\n",
            encoding="utf-8",
        )
        self.patchers = [
            patch.object(copilot, "ROOT", self.root),
            patch.object(copilot, "JOURNAL_DIR", self.root / "journal"),
            patch.object(copilot, "AI_CONVERSATIONS_DIR", self.root / "journal" / "ai-conversations"),
            patch.object(copilot, "export_codex_day_transcript", return_value=""),
            patch.object(copilot, "export_life_claude_renderer_day_transcript", return_value=("", 0, 0)),
            patch.object(copilot, "export_claude_code_day_transcript", return_value=("", 0, 0)),
            patch.object(copilot, "export_antigravity_day_transcript", return_value=("", 0, 0)),
            patch.object(copilot, "zshs_sync_day", return_value={"status": "pulled"}),
            patch.object(copilot, "export_zshs_claude_code_day_transcript", return_value=("", 0, 0)),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def test_writeback_writes_the_trace_and_one_from_kai_link(self) -> None:
        transcript = f"### zshs Codex Thread {THREAD}\n\n[11/17/26 9:43 AM] Henry: 工位上的问题\n"
        with patch.object(copilot, "export_zshs_codex_day_transcript", return_value=transcript):
            with redirect_stdout(io.StringIO()):
                result = copilot.writeback_ai_day(DAY, pull_zshs=True, pull_openclaw=False)
        trace = self.root / "journal" / "ai-conversations" / "2026" / "11" / "2026-11-17-zshs-codex-trace.md"
        self.assertEqual(result["zshs_status"], "pulled")
        self.assertTrue(trace.exists())
        self.assertIn("source: zshs-codex", trace.read_text(encoding="utf-8"))
        self.assertEqual(
            self.journal.read_text(encoding="utf-8").count("[[2026-11-17-zshs-codex-trace]]"),
            1,
        )

    def test_unreachable_zshs_is_reported_without_touching_the_trace(self) -> None:
        trace = self.root / "journal" / "ai-conversations" / "2026" / "11" / "2026-11-17-zshs-codex-trace.md"
        trace.parent.mkdir(parents=True)
        trace.write_text("archived\n", encoding="utf-8")
        with patch.object(copilot, "zshs_sync_day",
                          side_effect=copilot.ZshsImportUnavailable("connect timed out")), \
                patch.object(copilot, "export_codex_day_transcript",
                             return_value="[11/17/26 9:00 AM] Henry: 别的来源\n"):
            with redirect_stdout(io.StringIO()):
                result = copilot.writeback_ai_day(DAY, pull_zshs=True, pull_openclaw=False)
        self.assertEqual(result["zshs_status"], "unavailable")
        self.assertEqual(trace.read_text(encoding="utf-8"), "archived\n")

    def test_cli_defaults_to_reading_zshs_and_can_skip_it(self) -> None:
        parser = copilot.build_parser()
        self.assertFalse(parser.parse_args(["writeback-ai-day", "--date", "2026-11-17"]).no_zshs)
        self.assertTrue(parser.parse_args(["writeback-ai-day", "--date", "2026-11-17", "--no-zshs"]).no_zshs)




class ZshsBackfillTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.cache = self.root / "cache"
        self.codex = self.cache / "codex" / "sessions"
        self.claude = self.cache / "claude-code" / "projects"
        write_jsonl(self.codex / "2026" / "11" / "17" / "rollout-2026-11-17T09-43-00.jsonl", codex_rows())
        write_jsonl(self.claude / "-Users-zshs9-internship" / "22222222-2222-4222-8222-222222222222.jsonl", claude_rows())
        self.patchers = [
            patch.object(copilot, "ROOT", self.root),
            patch.object(copilot, "JOURNAL_DIR", self.root / "journal"),
            patch.object(copilot, "AI_CONVERSATIONS_DIR", self.root / "journal" / "ai-conversations"),
            patch.object(copilot, "ZSHS_CACHE_DIR", self.cache),
            patch.object(copilot, "ZSHS_CODEX_CACHE_DIR", self.codex),
            patch.object(copilot, "ZSHS_CLAUDE_CACHE_DIR", self.claude),
            patch.object(copilot, "ZSHS_CATPAW_CACHE_DIR", self.cache / "catpaw"),
            patch.object(copilot, "ZSHS_CATPAW_DB", "C:/Users/zshs9/catpaw.db"),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def test_backfill_writes_visible_corpus_index_and_daily_traces(self) -> None:
        def extract(_start, _end, source, **kwargs):
            if source == "codex":
                write_jsonl(
                    copilot.ZSHS_CODEX_CACHE_DIR / "2026" / "11" / "17" / "rollout-2026-11-17T09-43-00.jsonl",
                    codex_rows(),
                )
            elif source == "claude-code":
                write_jsonl(
                    copilot.ZSHS_CLAUDE_CACHE_DIR / "-Users-zshs9-internship" / "22222222-2222-4222-8222-222222222222.jsonl",
                    claude_rows(),
                )
            else:
                write_jsonl(copilot.ZSHS_CATPAW_CACHE_DIR / "c1.jsonl", catpaw_rows())
            archive = kwargs.get("archive_path")
            if archive is not None:
                archive.parent.mkdir(parents=True, exist_ok=True)
                archive.write_bytes(b"filtered-archive")
            return {"status": "pulled", "files": 1, "records": 2, "archive": str(archive or "")}

        with patch.object(copilot, "zshs_extract_range", side_effect=extract), \
                redirect_stdout(io.StringIO()):
            result = copilot.backfill_zshs(DAY, DAY)
        corpus = self.root / "journal" / "ai-conversations" / "zshs-internship-2026-11-17-to-2026-11-17"
        self.assertTrue((corpus / "visible" / "codex-filtered.tar.gz").exists())
        self.assertTrue((corpus / "visible" / "claude-code-filtered.tar.gz").exists())
        self.assertTrue((corpus / "visible" / "catpaw-filtered.tar.gz").exists())
        manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["files"]), 3)
        self.assertIn("visible user/assistant", manifest["scope"])
        self.assertIn("2026-11-17-zshs-codex-trace", (corpus / "index.md").read_text(encoding="utf-8"))
        trace = self.root / "journal" / "ai-conversations" / "2026" / "11" / "2026-11-17-zshs-codex-trace.md"
        self.assertIn("source: zshs-codex", trace.read_text(encoding="utf-8"))
        self.assertEqual(result["files"], 3)
        timeline = copilot.render_day_timeline(DAY)
        self.assertIn("zshs Codex", timeline)
        self.assertIn("zshs Claude Code", timeline)
        self.assertIn("zshs CatPaw", timeline)


if __name__ == "__main__":
    unittest.main()
