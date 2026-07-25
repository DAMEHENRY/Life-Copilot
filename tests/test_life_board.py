"""Focused unittest coverage for Life Board audit/writeback helpers."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

from scripts import copilot as copilot_module
from scripts.copilot import (
    audit_life_board,
    cmd_writeback_life_board,
    parse_life_board_last_updated,
    validate_life_board_text,
)


def _board_text(
    last_updated: str = "2026-06-04",
    status_line: str | None = "- **Status**: `active`",
) -> str:
    lines = [
        "# Life Board",
        "",
        "> Slow-variable active context map.",
        "",
        "---",
        "",
        "## Study / Reading",
        "",
        "- **Active question**: What does Henry retain from reading?",
        "- **Next artifact**: Write one short reflection.",
        "- **Stop condition**: The reading slot is stable.",
    ]
    if status_line is not None:
        lines.append(status_line)
    lines += [
        "",
        "---",
        "",
        "## Seeds",
        "",
        "Seed inventory lives in [[seeds/00-index|seeds/00-index]].",
        "",
        "---",
        "",
        f"*Last updated: [[{last_updated}]]*",
        "",
    ]
    return "\n".join(lines)


class TestLifeBoard(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.board_path = self.root / "life-board.md"
        self.journal_dir = self.root / "journal"
        self.patchers = [
            patch.object(copilot_module, "LIFE_BOARD_FILE", self.board_path),
            patch.object(copilot_module, "JOURNAL_DIR", self.journal_dir),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def set_board(self, text: str) -> None:
        self.board_path.write_text(text, encoding="utf-8")

    def write_journal(self, target: date, content: str) -> Path:
        path = (
            self.journal_dir
            / target.strftime("%Y")
            / target.strftime("%m")
            / f"{target.isoformat()}.md"
        )
        path.parent.mkdir(parents=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_parse_last_updated_wikilink_date(self):
        self.assertEqual(
            parse_life_board_last_updated(_board_text("2026-06-04")),
            date(2026, 6, 4),
        )

    def test_audit_due_after_seven_days(self):
        self.set_board(_board_text("2026-06-04"))
        result = audit_life_board(date(2026, 6, 11))
        self.assertTrue(result["needs_audit"])
        self.assertTrue(result["due"])
        self.assertEqual(result["last_updated"], "2026-06-04")
        self.assertEqual(result["days_since_update"], 7)
        self.assertIn("last_updated_older_than_7_days", result["reasons"])

    def test_audit_triggers_on_explicit_diary_board_mention(self):
        self.set_board(_board_text("2026-07-05"))
        self.write_journal(
            date(2026, 7, 7),
            "#diary\n\nToday I need to discuss this board 机制 and review.\n",
        )
        result = audit_life_board(date(2026, 7, 7))
        self.assertTrue(result["needs_audit"])
        self.assertFalse(result["due"])
        self.assertTrue(result["explicit_trigger"])
        self.assertIn("journal_explicit_trigger", result["reasons"])

    def test_audit_noop_when_recent_and_no_trigger(self):
        self.set_board(_board_text("2026-07-06"))
        self.write_journal(
            date(2026, 7, 7),
            "#diary\n\n普通一天，没有项目审计。\n",
        )
        result = audit_life_board(date(2026, 7, 7))
        self.assertFalse(result["needs_audit"])
        self.assertFalse(result["due"])
        self.assertFalse(result["explicit_trigger"])
        self.assertEqual(result["reasons"], [])

    def test_invalid_board_missing_status_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing field: Status"):
            validate_life_board_text(_board_text(status_line=None))

    def test_writeback_rejects_invalid_board_without_overwriting(self):
        self.set_board(_board_text("2026-06-04"))
        original = self.board_path.read_text(encoding="utf-8")
        input_path = self.root / "replacement.md"
        input_path.write_text(_board_text(status_line=None), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "missing field: Status"):
            cmd_writeback_life_board(
                SimpleNamespace(date="2026-07-07", input_file=str(input_path))
            )
        self.assertEqual(self.board_path.read_text(encoding="utf-8"), original)

    def test_writeback_valid_board_updates_last_updated(self):
        self.set_board(_board_text("2026-06-04"))
        input_path = self.root / "replacement.md"
        input_path.write_text(_board_text("2026-06-04"), encoding="utf-8")
        cmd_writeback_life_board(
            SimpleNamespace(date="2026-07-07", input_file=str(input_path))
        )
        updated = self.board_path.read_text(encoding="utf-8")
        self.assertIn("*Last updated: [[2026-07-07]]*", updated)
        self.assertNotIn("*Last updated: [[2026-06-04]]*", updated)


if __name__ == "__main__":
    unittest.main()
