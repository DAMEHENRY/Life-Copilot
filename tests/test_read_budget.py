"""Read budget: every must-read file has to reach an agent whole, or come with a reading plan."""

from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

from scripts import copilot as copilot_module
from scripts.copilot import (
    READ_BUDGET_BYTES,
    READ_CAP_BYTES,
    audit_read_budget,
    cmd_writeback_ai_day,
    read_budget_plan,
    read_budget_status,
)

# Tracked must-read files that were already over budget when the check was
# introduced (2026-09-21). They may shrink but not grow, so anything added to
# them has to be paid for by cutting something else; once a file is back under
# budget its entry has to go.
OVER_BUDGET_BASELINE = {
    "prompts/diary-mode.md": 26_358,
}


def _line_sizes(data: bytes) -> list[int]:
    lines = data.split(b"\n")
    if lines[-1] == b"":
        lines.pop()
    return [len(line) + 1 for line in lines]


class TestReadBudgetPlan(unittest.TestCase):
    def test_limit_counts_bytes_so_chinese_reaches_it_first(self) -> None:
        chinese = ("中" * 99 + "\n") * 90  # 8,910 characters, 26,820 bytes
        ascii_text = ("x" * 99 + "\n") * 90  # same character count, 9,000 bytes
        self.assertEqual(read_budget_status(len(chinese.encode())), "near")
        self.assertEqual(read_budget_status(len(ascii_text.encode())), "ok")
        self.assertEqual(read_budget_status(READ_CAP_BYTES + 1), "over")

    def test_ranges_cover_every_line_once_and_each_fits(self) -> None:
        data = b"".join(
            ("行" * (40 + (n * 37) % 900) + "\n").encode() for n in range(400)
        )
        ranges, oversize = read_budget_plan(data)
        sizes = _line_sizes(data)
        covered = [n for a, b in ranges for n in range(a, b + 1)]
        self.assertEqual(covered, list(range(1, len(sizes) + 1)))
        for a, b in ranges:
            self.assertLessEqual(sum(sizes[a - 1:b]), READ_BUDGET_BYTES)
        self.assertEqual(oversize, [])
        self.assertGreater(len(ranges), 1)

    def test_last_line_counts_without_trailing_newline(self) -> None:
        ranges, _ = read_budget_plan(b"one\ntwo\nthree")
        self.assertEqual(ranges, [(1, 3)])

    def test_line_longer_than_budget_gets_a_range_of_its_own(self) -> None:
        data = b"short\n" + b"x" * (READ_BUDGET_BYTES + 10) + b"\nshort\n"
        ranges, oversize = read_budget_plan(data)
        self.assertEqual(ranges, [(1, 1), (2, 2), (3, 3)])
        self.assertEqual(oversize, [2])

    def test_empty_file_has_nothing_to_read(self) -> None:
        self.assertEqual(read_budget_plan(b""), ([], []))


class TestAuditReadBudget(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        journal = self.root / "journal"
        (self.root / "prompts").mkdir()
        (journal / "2026" / "09").mkdir(parents=True)
        (journal / "ai-conversations" / "2026" / "09").mkdir(parents=True)
        self.patchers = [
            patch.object(copilot_module, "ROOT", self.root),
            patch.object(copilot_module, "JOURNAL_DIR", journal),
            patch.object(copilot_module, "LIFE_BOARD_FILE", self.root / "life-board.md"),
            patch.object(copilot_module, "MEMORY_FILE", journal / "memory.md"),
            patch.object(copilot_module, "AI_CONVERSATIONS_DIR", journal / "ai-conversations"),
            patch.object(copilot_module, "PEOPLE_DIR", journal / "people"),
        ]
        for patcher in self.patchers:
            patcher.start()
        (self.root / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
        (self.root / "prompts" / "diary-mode.md").write_text("# Diary\n", encoding="utf-8")
        # 8,910 characters but 26,820 bytes: over budget only if bytes are counted.
        (self.root / "life-board.md").write_text(("中" * 99 + "\n") * 90, encoding="utf-8")
        (journal / "memory.md").write_text(("- [2026-09-20] 记忆\n" * 3000), encoding="utf-8")
        (journal / "2026" / "09" / "2026-09-20.md").write_text("#diary\n", encoding="utf-8")
        trace_dir = journal / "ai-conversations" / "2026" / "09"
        (trace_dir / "2026-09-20-codex-trace.md").write_text("trace\n", encoding="utf-8")
        (trace_dir / "2026-09-19-codex-trace.md").write_text("other day\n", encoding="utf-8")

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def test_reports_missing_files_and_only_the_target_days_traces(self) -> None:
        result = audit_read_budget(date(2026, 9, 20))
        by_path = {item["path"]: item for item in result["files"]}
        self.assertEqual(by_path["CLAUDE.md"]["status"], "missing")
        self.assertIn("journal/2026/09/2026-09-20.md", by_path)
        self.assertIn("journal/ai-conversations/2026/09/2026-09-20-codex-trace.md", by_path)
        self.assertNotIn("journal/ai-conversations/2026/09/2026-09-19-codex-trace.md", by_path)
        self.assertEqual(by_path["life-board.md"]["status"], "near")
        memory = by_path["journal/memory.md"]
        self.assertEqual(memory["status"], "over")
        self.assertEqual(memory["reads"], len(memory["ranges"]))
        self.assertEqual(result["counts"]["missing"], 1)

    def test_without_a_date_only_the_standing_files_are_checked(self) -> None:
        paths = [item["path"] for item in audit_read_budget()["files"]]
        self.assertEqual(
            paths,
            ["AGENTS.md", "CLAUDE.md", "prompts/diary-mode.md", "life-board.md", "journal/memory.md"],
        )


class TestWritebackAiDayReadBudget(unittest.TestCase):
    def _run(self, pages: list | None = None, **audit_patch) -> list[str]:
        args = SimpleNamespace(date="2026-09-20")
        out = io.StringIO()
        with patch.object(copilot_module, "writeback_ai_day", return_value={"journal": "/vault/journal/day.md"}), \
                patch.object(copilot_module, "audit_read_budget", **audit_patch), \
                patch.object(copilot_module, "pages_mentioned", return_value=pages or []), \
                redirect_stdout(out):
            cmd_writeback_ai_day(args)
        return out.getvalue().splitlines()

    def test_budget_is_listed_before_the_journal_path(self) -> None:
        result = {
            "counts": {"over": 1, "near": 0, "ok": 0, "missing": 0},
            "files": [{
                "path": "journal/memory.md", "status": "over", "bytes": 90_000,
                "percent_of_cap": 300, "reads": 4, "ranges": ["1-10", "11-20", "21-30", "31-40"],
                "oversize_lines": [],
            }],
        }
        lines = self._run(return_value=result)
        self.assertTrue(lines[0].startswith("Read budget: 1 over cap"))
        self.assertIn("read in 4 parts", lines[1])
        self.assertEqual(lines[-1], "/vault/journal/day.md")

    def test_mentioned_people_pages_are_named_before_the_journal_path(self) -> None:
        result = {"counts": {"over": 0, "near": 0, "ok": 1, "missing": 0}, "files": []}
        pages = [{"slug": "zheng-chen", "path": Path("p"), "name": "郑宸", "mentions": 3}]
        lines = self._run(pages=pages, return_value=result)
        self.assertEqual(lines[1], "People pages mentioned today (read before the analysis): zheng-chen (郑宸 ×3)")
        self.assertEqual(lines[-1], "/vault/journal/day.md")

    def test_a_failed_budget_check_does_not_fail_the_archive(self) -> None:
        lines = self._run(side_effect=OSError("disk"))
        self.assertEqual(lines, ["Read budget: unavailable (disk)", "/vault/journal/day.md"])


class TestTrackedMustReadFiles(unittest.TestCase):
    """Guards the files every agent reads in full; only these are in git."""

    def test_each_fits_one_read_or_does_not_grow(self) -> None:
        tracked = [ROOT / "AGENTS.md", ROOT / "CLAUDE.md", *sorted((ROOT / "prompts").glob("*.md"))]
        for path in tracked:
            name = path.relative_to(ROOT).as_posix()
            size = len(path.read_bytes())
            with self.subTest(file=name, bytes=size):
                if name in OVER_BUDGET_BASELINE:
                    self.assertLessEqual(
                        size, OVER_BUDGET_BASELINE[name],
                        f"{name} grew past its baseline; cut something before adding",
                    )
                    self.assertGreater(
                        size, READ_BUDGET_BYTES,
                        f"{name} is back under budget; remove it from OVER_BUDGET_BASELINE",
                    )
                else:
                    self.assertLessEqual(size, READ_BUDGET_BYTES, f"{name} no longer fits one read")


if __name__ == "__main__":
    unittest.main()
