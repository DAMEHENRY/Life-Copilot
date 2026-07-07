"""Focused tests for Life Board audit/writeback helpers.

Uses temporary directories — no real board or diary files are modified.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from types import SimpleNamespace
from pathlib import Path

# Add project root to path so we can import copilot
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

from scripts.copilot import (
    audit_life_board,
    cmd_writeback_life_board,
    parse_life_board_last_updated,
    validate_life_board_text,
)
from scripts import copilot as copilot_module


def _board_text(last_updated: str = "2026-06-04", status_line: str | None = "- **Status**: `active`") -> str:
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


def _patch_vault(monkeypatch, tmp_path: Path, board_text: str):
    board_path = tmp_path / "life-board.md"
    journal_dir = tmp_path / "journal"
    board_path.write_text(board_text, encoding="utf-8")
    monkeypatch.setattr(copilot_module, "LIFE_BOARD_FILE", board_path)
    monkeypatch.setattr(copilot_module, "JOURNAL_DIR", journal_dir)
    return board_path, journal_dir


def _write_journal(journal_dir: Path, target: date, content: str) -> Path:
    jp = journal_dir / target.strftime("%Y") / target.strftime("%m") / f"{target.isoformat()}.md"
    jp.parent.mkdir(parents=True)
    jp.write_text(content, encoding="utf-8")
    return jp


def test_parse_last_updated_wikilink_date():
    assert parse_life_board_last_updated(_board_text("2026-06-04")) == date(2026, 6, 4)


def test_audit_due_after_seven_days(monkeypatch, tmp_path):
    _patch_vault(monkeypatch, tmp_path, _board_text("2026-06-04"))

    result = audit_life_board(date(2026, 6, 11))

    assert result["needs_audit"] is True
    assert result["due"] is True
    assert result["last_updated"] == "2026-06-04"
    assert result["days_since_update"] == 7
    assert "last_updated_older_than_7_days" in result["reasons"]


def test_audit_triggers_on_explicit_diary_board_mention(monkeypatch, tmp_path):
    _, journal_dir = _patch_vault(monkeypatch, tmp_path, _board_text("2026-07-05"))
    _write_journal(
        journal_dir,
        date(2026, 7, 7),
        "#diary\n\nToday I need to discuss this board 机制 and review.\n",
    )

    result = audit_life_board(date(2026, 7, 7))

    assert result["needs_audit"] is True
    assert result["due"] is False
    assert result["explicit_trigger"] is True
    assert "journal_explicit_trigger" in result["reasons"]


def test_audit_noop_when_recent_and_no_trigger(monkeypatch, tmp_path):
    _, journal_dir = _patch_vault(monkeypatch, tmp_path, _board_text("2026-07-06"))
    _write_journal(journal_dir, date(2026, 7, 7), "#diary\n\n普通一天，没有项目审计。\n")

    result = audit_life_board(date(2026, 7, 7))

    assert result["needs_audit"] is False
    assert result["due"] is False
    assert result["explicit_trigger"] is False
    assert result["reasons"] == []


def test_invalid_board_missing_status_is_rejected():
    try:
        validate_life_board_text(_board_text(status_line=None))
        assert False, "Should have rejected missing status"
    except ValueError as exc:
        assert "missing field: Status" in str(exc)


def test_writeback_rejects_invalid_board_without_overwriting(monkeypatch, tmp_path):
    board_path, _ = _patch_vault(monkeypatch, tmp_path, _board_text("2026-06-04"))
    original = board_path.read_text(encoding="utf-8")
    input_path = tmp_path / "replacement.md"
    input_path.write_text(_board_text(status_line=None), encoding="utf-8")

    try:
        cmd_writeback_life_board(SimpleNamespace(date="2026-07-07", input_file=str(input_path)))
        assert False, "Should have rejected invalid board"
    except ValueError as exc:
        assert "missing field: Status" in str(exc)

    assert board_path.read_text(encoding="utf-8") == original


def test_writeback_valid_board_updates_last_updated(monkeypatch, tmp_path):
    board_path, _ = _patch_vault(monkeypatch, tmp_path, _board_text("2026-06-04"))
    input_path = tmp_path / "replacement.md"
    input_path.write_text(_board_text("2026-06-04"), encoding="utf-8")

    cmd_writeback_life_board(SimpleNamespace(date="2026-07-07", input_file=str(input_path)))

    updated = board_path.read_text(encoding="utf-8")
    assert "*Last updated: [[2026-07-07]]*" in updated
    assert "*Last updated: [[2026-06-04]]*" not in updated


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
