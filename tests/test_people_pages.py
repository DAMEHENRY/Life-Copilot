"""People pages: shape checks, verbatim quotes, history, and finding the pages a day mentions."""

from __future__ import annotations

import hashlib
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

from scripts import copilot as copilot_module
from scripts.copilot import (
    format_pages_mentioned,
    maintain_people_page,
    pages_mentioned,
    read_budget_paths,
    validate_people_page,
)

DIARY = """#diary
He said the edge is in high frequency and the study of market microstructure.
He also said the loop can sit in front, or it can optimise within the universe you selected.
"""
TRACE = "[9/20/26 4:17 PM] Henry: 他说不一定，这种很多时候都是尝试出来的\n"


def _page(
    updated: str = "2026-09-20",
    aliases: str = "  - 郑宸\n  - Zhen",
    evidence: str | None = None,
    open_questions: str = "- 算子库那段还没弄懂。\n",
) -> str:
    if evidence is None:
        evidence = (
            "- **看重高频** · 支持 1\n"
            "  - He said the edge is in high frequency — [[2026-09-20]]\n"
            "- **loop 可以放在前面** · 支持 1\n"
            "  - the loop can sit in front … the universe you selected — [[2026-09-20]]\n"
            "  - 他说不一定，这种很多时候都是尝试出来的 — [[2026-09-20-codex-trace]] 16:17\n"
        )
    return (
        f"---\nname: 郑宸\naliases:\n{aliases}\nquestion: 郑宸是谁？\nupdated: {updated}\n---\n\n"
        f"# 郑宸\n\n## 答案\n\n他做量化。\n\n## 证据\n\n{evidence}\n## 悬着的\n\n{open_questions}"
    )


class PeopleDirCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.journal = root / "journal"
        self.people = self.journal / "people"
        self.trace_dir = self.journal / "ai-conversations" / "2026" / "09"
        (self.journal / "2026" / "09").mkdir(parents=True)
        self.trace_dir.mkdir(parents=True)
        (self.journal / "2026" / "09" / "2026-09-20.md").write_text(DIARY, encoding="utf-8")
        (self.trace_dir / "2026-09-20-codex-trace.md").write_text(TRACE, encoding="utf-8")
        self.patchers = [
            patch.object(copilot_module, "JOURNAL_DIR", self.journal),
            patch.object(copilot_module, "AI_CONVERSATIONS_DIR", self.journal / "ai-conversations"),
            patch.object(copilot_module, "PEOPLE_DIR", self.people),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()


class TestValidatePeoplePage(PeopleDirCase):
    def test_valid_page_counts_beliefs_and_quotes(self) -> None:
        self.assertEqual(validate_people_page(_page()), {"beliefs": 2, "quotes": 3})

    def test_quote_must_be_verbatim_in_its_source(self) -> None:
        evidence = "- **看重高频** · 支持 1\n  - He said the edge is in low frequency — [[2026-09-20]]\n"
        with self.assertRaisesRegex(ValueError, "not found verbatim in \\[\\[2026-09-20\\]\\]"):
            validate_people_page(_page(evidence=evidence))

    def test_ellipsis_fragments_must_appear_in_order(self) -> None:
        evidence = "- **顺序** · 支持 1\n  - the universe you selected … the loop can sit in front — [[2026-09-20]]\n"
        with self.assertRaisesRegex(ValueError, "not found verbatim"):
            validate_people_page(_page(evidence=evidence))

    def test_evidence_must_cite_a_diary_or_a_trace(self) -> None:
        evidence = "- **别的来源** · 支持 1\n  - He said the edge is in high frequency — [[jit-finance-denoising-seed]]\n"
        with self.assertRaisesRegex(ValueError, "must cite a diary date or a daily trace"):
            validate_people_page(_page(evidence=evidence))

    def test_all_shape_problems_are_reported_together(self) -> None:
        text = _page(evidence="- 没有计数的判断\n").replace("## 悬着的", "## 其他")
        with self.assertRaises(ValueError) as caught:
            validate_people_page(text)
        message = str(caught.exception)
        self.assertIn("without a 支持 count", message)
        self.assertIn("missing section ## 悬着的", message)

    def test_aliases_that_would_match_too_much_are_rejected(self) -> None:
        with self.assertRaises(ValueError) as caught:
            validate_people_page(_page(aliases="  - 贺\n  - He"))
        self.assertIn("'贺' is shorter than two Chinese characters", str(caught.exception))
        self.assertIn("'He' is shorter than three characters", str(caught.exception))


class TestMaintainPeoplePage(PeopleDirCase):
    def _sha(self, slug: str = "zheng-chen") -> str:
        return hashlib.sha256((self.people / f"{slug}.md").read_bytes()).hexdigest()

    def test_create_then_rewrite_keeps_the_previous_version(self) -> None:
        first = _page(updated="2026-09-20")
        self.assertEqual(maintain_people_page("zheng-chen", first)["action"], "created")
        second = _page(updated="2026-09-21", open_questions="- 已经问过了。\n")
        result = maintain_people_page("zheng-chen", second, base_sha256=self._sha())
        self.assertEqual(result["action"], "updated")
        history = self.people / ".history" / "zheng-chen" / "2026-09-20.md"
        self.assertEqual(result["history"], str(history))
        self.assertEqual(history.read_text(encoding="utf-8"), first)
        self.assertEqual((self.people / "zheng-chen.md").read_text(encoding="utf-8"), second)

    def test_rewrite_needs_the_hash_of_the_version_that_was_read(self) -> None:
        original = _page()
        maintain_people_page("zheng-chen", original)
        newer = _page(updated="2026-09-21")
        with self.assertRaisesRegex(ValueError, "pass --base-sha256"):
            maintain_people_page("zheng-chen", newer)
        with self.assertRaisesRegex(ValueError, "changed since it was read"):
            maintain_people_page("zheng-chen", newer, base_sha256="0" * 64)
        self.assertEqual((self.people / "zheng-chen.md").read_text(encoding="utf-8"), original)
        self.assertFalse((self.people / ".history").exists())

    def test_dry_run_writes_nothing(self) -> None:
        result = maintain_people_page("zheng-chen", _page(), dry_run=True)
        self.assertEqual(result["action"], "created")
        self.assertFalse((self.people / "zheng-chen.md").exists())

    def test_same_text_is_a_no_op(self) -> None:
        maintain_people_page("zheng-chen", _page())
        result = maintain_people_page("zheng-chen", _page(), base_sha256=self._sha())
        self.assertEqual(result["action"], "no-op")
        self.assertFalse((self.people / ".history").exists())

    def test_history_names_do_not_collide(self) -> None:
        maintain_people_page("zheng-chen", _page(open_questions="- 一\n"))
        maintain_people_page("zheng-chen", _page(open_questions="- 二\n"), base_sha256=self._sha())
        result = maintain_people_page("zheng-chen", _page(open_questions="- 三\n"), base_sha256=self._sha())
        self.assertTrue(str(result["history"]).endswith("2026-09-20-2.md"))

    def test_slug_must_be_kebab_case(self) -> None:
        with self.assertRaisesRegex(ValueError, "kebab-case"):
            maintain_people_page("郑宸", _page())

    def test_an_invalid_page_is_never_written(self) -> None:
        evidence = "- **看重高频** · 支持 1\n  - invented words — [[2026-09-20]]\n"
        with self.assertRaises(ValueError):
            maintain_people_page("zheng-chen", _page(evidence=evidence))
        self.assertFalse((self.people / "zheng-chen.md").exists())


class TestPagesMentioned(PeopleDirCase):
    def _write_page(self) -> None:
        self.people.mkdir(parents=True, exist_ok=True)
        (self.people / "zheng-chen.md").write_text(
            _page(aliases="  - 郑宸\n  - Zhen\n  - zhen chen"), encoding="utf-8"
        )

    def test_counts_each_mention_once_and_respects_word_boundaries(self) -> None:
        self._write_page()
        (self.journal / "2026" / "09" / "2026-09-20.md").write_text(
            "郑宸说了两次，郑宸。Zhen agreed. zhen chen again. Zhenyu is someone else.", encoding="utf-8"
        )
        (self.trace_dir / "2026-09-20-codex-trace.md").write_text("", encoding="utf-8")
        found = pages_mentioned(date(2026, 9, 20))
        self.assertEqual([(f["slug"], f["mentions"]) for f in found], [("zheng-chen", 4)])
        self.assertEqual(
            format_pages_mentioned(found),
            ["People pages mentioned today (read before the analysis): zheng-chen (郑宸 ×4)"],
        )

    def test_an_unreadable_page_is_reported_not_skipped(self) -> None:
        self.people.mkdir(parents=True)
        (self.people / "broken.md").write_text("# no yaml\n", encoding="utf-8")
        found = pages_mentioned(date(2026, 9, 20))
        self.assertEqual(found[0]["slug"], "broken")
        self.assertIn("could not be read", format_pages_mentioned(found)[0])

    def test_the_read_plan_includes_the_pages_the_day_mentions(self) -> None:
        self._write_page()
        (self.journal / "2026" / "09" / "2026-09-20.md").write_text("今天和郑宸聊了", encoding="utf-8")
        with patch.object(copilot_module, "ROOT", self.journal.parent):
            paths = read_budget_paths(date(2026, 9, 20))
        self.assertIn(self.people / "zheng-chen.md", paths)
        self.assertNotIn(self.people / "zheng-chen.md", read_budget_paths())


if __name__ == "__main__":
    unittest.main()
