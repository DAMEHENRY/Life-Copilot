"""Focused tests for Daily Suggestion and writeback-thought changes.

Uses temporary directories — no real diary files are created.
"""

from __future__ import annotations

import sys
import os
import tempfile
import textwrap
from datetime import date
from pathlib import Path

# Add project root to path so we can import copilot
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

from scripts.copilot import (
    append_thought_to_journal,
    render_diary_from_template,
    write_daily_suggestion,
)
from scripts import copilot as copilot_module

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEMPLATE_MINIMAL = textwrap.dedent("""\
    #diary
    #  📅  2026-06-06
    ## 🧭 Daily Suggestion

    ## 💭 Thoughts & Reflections

    ## 📸 Daily Moment
    >

    ## 💬 From Kai

    ## 🧭 Tomorrow Projection Input
    *Low-friction input surface for tomorrow's conversational projection. Not a task list or script gate.*
    - **Tomorrow anchor**:
    - **Context / track**:
    - **Known limits**:
    - **Do-not-expand**:

    ## 🏃‍♂️ Habits (Optional)
    - [ ] Sports:
    - [ ] Reading:
    - [ ] Podcast:

    ## ✍️ Writing State
    - Time:
    - Place:
    - Mood:

    ## What Life Copilot Said
""")


def _journal_with_sections(*sections: str) -> str:
    """Build a minimal journal with given section headings."""
    lines = ["#diary\n# 📅 2026-06-06\n"]
    for s in sections:
        lines.append(f"## {s}\n\n")
    return "".join(lines)


# ---------------------------------------------------------------------------
# Tests: writeback-thought without Daily Log
# ---------------------------------------------------------------------------

class TestWritebackThoughtWithoutDailyLog:
    """writeback-thought should work when no Daily Log section exists."""

    def test_writes_to_thoughts_and_reflections(self):
        journal = _journal_with_sections(
            "🧭 Daily Suggestion",
            "💭 Thoughts & Reflections",
            "What Life Copilot Said",
        )
        result = append_thought_to_journal(journal, "测试标题", "测试内容")
        assert "测试标题" in result
        assert "测试内容" in result
        assert "💭 Thoughts & Reflections" in result

    def test_no_daily_log_section_required(self):
        """Should not raise even when Daily Log is absent."""
        journal = _journal_with_sections(
            "🧭 Daily Suggestion",
            "💭 Thoughts & Reflections",
        )
        # Must not raise
        result = append_thought_to_journal(journal, "标题", "内容")
        assert "标题" in result

    def test_copilot_analysis_still_rejected(self):
        """Guardrail: Copilot analysis content must still be rejected."""
        journal = _journal_with_sections("💭 Thoughts & Reflections")
        try:
            append_thought_to_journal(journal, "分析", "## 🧭 Copilot 建议\n你今天...")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Copilot analysis" in str(e)


# ---------------------------------------------------------------------------
# Tests: render_diary_from_template
# ---------------------------------------------------------------------------

class TestRenderDiaryFromTemplate:

    def test_renders_date_correctly(self):
        target = date(2026, 6, 7)
        rendered = render_diary_from_template(target)
        assert "2026-06-07" in rendered
        assert "{{time:HH:mm}}" not in rendered
        assert "⏰" not in rendered

    def test_no_creation_time_line(self):
        """Rendered diary must not contain a creation time line or placeholder."""
        target = date(2026, 6, 7)
        rendered = render_diary_from_template(target)
        assert "⏰" not in rendered
        assert "{{time:HH:mm}}" not in rendered
        # Should not contain any HH:mm like "22:00" or "00:00"
        import re
        assert not re.search(r"\d{2}:\d{2}", rendered)

    def test_contains_daily_suggestion_section(self):
        target = date(2026, 6, 7)
        rendered = render_diary_from_template(target)
        assert "## 🧭 Daily Suggestion" in rendered


# ---------------------------------------------------------------------------
# Tests: write_daily_suggestion
# ---------------------------------------------------------------------------

class TestWriteDailySuggestion:

    def test_creates_section_in_new_diary(self):
        journal = _journal_with_sections(
            "🧭 Daily Suggestion",
            "💭 Thoughts & Reflections",
        )
        result = write_daily_suggestion(journal, "建议内容", date(2026, 6, 6))
        assert "## 🧭 Daily Suggestion" in result
        assert "建议内容" in result
        assert "> Generated from [[2026-06-06]] diary analysis." in result

    def test_inserts_before_thoughts_if_section_missing(self):
        """If old diary has no Daily Suggestion, insert before Thoughts."""
        journal = _journal_with_sections(
            "💭 Thoughts & Reflections",
            "What Life Copilot Said",
        )
        result = write_daily_suggestion(journal, "建议", date(2026, 6, 6))
        # Daily Suggestion should appear before Thoughts
        ds_pos = result.index("## 🧭 Daily Suggestion")
        tr_pos = result.index("## 💭 Thoughts & Reflections")
        assert ds_pos < tr_pos

    def test_idempotent_re_run_no_duplicate(self):
        """Running twice with same source-date should not duplicate sections."""
        journal = _journal_with_sections(
            "🧭 Daily Suggestion",
            "💭 Thoughts & Reflections",
        )
        first = write_daily_suggestion(journal, "建议v1", date(2026, 6, 6))
        second = write_daily_suggestion(first, "建议v2", date(2026, 6, 6))
        # Should still have exactly one Daily Suggestion heading
        assert second.count("## 🧭 Daily Suggestion") == 1
        # Content should be updated to v2
        assert "建议v2" in second
        assert "建议v1" not in second

    def test_preserves_other_sections(self):
        """Other sections must not be modified."""
        journal = _journal_with_sections(
            "🧭 Daily Suggestion",
            "💭 Thoughts & Reflections",
            "📸 Daily Moment\n> A nice photo",
            "What Life Copilot Said\nOld analysis here.",
        )
        result = write_daily_suggestion(journal, "新建议", date(2026, 6, 6))
        assert "> A nice photo" in result
        assert "Old analysis here." in result

    def test_legacy_daily_log_not_deleted(self):
        """Old diary with Daily Log should keep that content."""
        journal = textwrap.dedent("""\
            #diary
            # 📅 2026-06-06
            ## 📝 Daily Log
            - [ ] 旧任务

            ## 💭 Thoughts & Reflections

            ## What Life Copilot Said
        """)
        result = write_daily_suggestion(journal, "建议", date(2026, 6, 6))
        assert "- [ ] 旧任务" in result
        assert "## 📝 Daily Log" in result

    def test_what_life_copilot_said_independent(self):
        """Daily Suggestion and What Life Copilot Said are independent."""
        journal = _journal_with_sections(
            "🧭 Daily Suggestion",
            "💭 Thoughts & Reflections",
            "What Life Copilot Said\n分析内容",
        )
        result = write_daily_suggestion(journal, "执行建议", date(2026, 6, 6))
        # Both should exist independently
        assert "执行建议" in result
        assert "分析内容" in result
        # Daily Suggestion should have provenance
        assert "> Generated from [[2026-06-06]]" in result
        # What Life Copilot Said should not contain provenance
        copilot_section = result[result.index("## What Life Copilot Said"):]
        assert "Generated from" not in copilot_section

    def test_refuses_overwrite_without_force(self):
        """Should refuse to overwrite suggestion from different source."""
        journal = _journal_with_sections(
            "🧭 Daily Suggestion",
            "💭 Thoughts & Reflections",
        )
        first = write_daily_suggestion(journal, "来自06-05", date(2026, 6, 5))
        try:
            write_daily_suggestion(first, "来自06-06", date(2026, 6, 6))
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "06-05" in str(e)

    def test_force_overwrite_different_source(self):
        """--force should allow overwriting from different source."""
        journal = _journal_with_sections(
            "🧭 Daily Suggestion",
            "💭 Thoughts & Reflections",
        )
        first = write_daily_suggestion(journal, "旧建议", date(2026, 6, 5))
        result = write_daily_suggestion(first, "新建议", date(2026, 6, 6), force=True)
        assert "新建议" in result
        assert "旧建议" not in result
        assert "> Generated from [[2026-06-06]]" in result


class TestWriteDailySuggestionCommand:
    """Exercise parser dispatch and filesystem creation in an isolated vault."""

    def test_creates_next_day_diary_via_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal_dir = root / "journal"
            templates_dir = root / "templates"
            templates_dir.mkdir(parents=True)
            (templates_dir / "daily-log.md").write_text(
                TEMPLATE_MINIMAL
                .replace("2026-06-06", "{{date:YYYY-MM-DD}}"),
                encoding="utf-8",
            )
            input_file = root / "suggestion.md"
            input_file.write_text("完成一个最小动作。", encoding="utf-8")

            old_journal_dir = copilot_module.JOURNAL_DIR
            old_templates_dir = copilot_module.TEMPLATES_DIR
            try:
                copilot_module.JOURNAL_DIR = journal_dir
                copilot_module.TEMPLATES_DIR = templates_dir
                args = copilot_module.build_parser().parse_args([
                    "writeback-daily-suggestion",
                    "--source-date",
                    "2026-06-06",
                    "--input-file",
                    str(input_file),
                ])
                args.func(args)
            finally:
                copilot_module.JOURNAL_DIR = old_journal_dir
                copilot_module.TEMPLATES_DIR = old_templates_dir

            target = journal_dir / "2026" / "06" / "2026-06-07.md"
            assert target.exists()
            text = target.read_text(encoding="utf-8")
            assert "#  📅  2026-06-07" in text
            assert "⏰" not in text
            assert "{{time:HH:mm}}" not in text
            assert "完成一个最小动作。" in text
            assert "> Generated from [[2026-06-06]] diary analysis." in text


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
