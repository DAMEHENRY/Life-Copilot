"""People pages: shape checks, verbatim quotes, history, the pages a day mentions, and a page's trail."""

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
    migrate_page_to_trail,
    pages_mentioned,
    read_budget_paths,
    validate_people_page,
    write_page_day,
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
            patch.object(copilot_module, "BOOKS_DIR", self.journal / "books"),
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
        with self.assertRaisesRegex(ValueError, "not found verbatim in Henry's own words in \\[\\[2026-09-20\\]\\]"):
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


class TestHenrysOwnWords(PeopleDirCase):
    """Evidence and mentions come from what Henry wrote or said, not from Copilot or other AIs."""

    def _quote(self, text: str, link: str) -> str:
        return _page(evidence=f"- **出处** · 支持 1\n  - {text} — [[{link}]]\n")

    def test_a_quote_from_an_ai_message_is_rejected(self) -> None:
        (self.trace_dir / "2026-09-20-codex-trace.md").write_text(
            TRACE + "[9/20/26 4:18 PM] Codex: 这是模型自己的分析\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "Henry's own words"):
            validate_people_page(self._quote("这是模型自己的分析", "2026-09-20-codex-trace"))

    def test_copilot_sections_and_the_merged_capture_are_not_henrys_words(self) -> None:
        diary = (
            "#diary\n## 💭 Thoughts & Reflections\nHenry wrote this line.\n"
            "### 对话补记\n> capture-id: chat-capture-2026-09-20\nCopilot transcribed this line.\n"
            "> capture-end: chat-capture-2026-09-20\n## What Life Copilot Said\nCopilot said this line.\n"
        )
        (self.journal / "2026" / "09" / "2026-09-20.md").write_text(diary, encoding="utf-8")
        validate_people_page(self._quote("Henry wrote this line.", "2026-09-20"))
        for line in ("Copilot transcribed this line.", "Copilot said this line."):
            with self.subTest(line=line), self.assertRaisesRegex(ValueError, "Henry's own words"):
                validate_people_page(self._quote(line, "2026-09-20"))

    def test_manual_blocks_with_a_narrow_space_before_pm_still_count(self) -> None:
        (self.trace_dir / "2026-09-20-codex-trace.md").write_text(
            "[9/20/26 4:17\u202fPM] Henry: 手工补的一句\n", encoding="utf-8"
        )
        validate_people_page(self._quote("手工补的一句", "2026-09-20-codex-trace"))

    def test_mentions_count_only_henrys_words(self) -> None:
        self.people.mkdir(parents=True)
        (self.people / "zheng-chen.md").write_text(_page(), encoding="utf-8")
        (self.journal / "2026" / "09" / "2026-09-20.md").write_text(
            "## 💭 Thoughts & Reflections\n今天见了郑宸。\n## What Life Copilot Said\n郑宸郑宸郑宸\n", encoding="utf-8"
        )
        (self.trace_dir / "2026-09-20-codex-trace.md").write_text(
            "[9/20/26 4:17 PM] Henry: 郑宸说的\n[9/20/26 4:18 PM] Codex: 郑宸郑宸\n", encoding="utf-8"
        )
        self.assertEqual(pages_mentioned(date(2026, 9, 20))[0]["mentions"], 2)


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


def _book(trail: str = "- 06-01 睡前读了十分钟 — [[2026-09-20-codex-trace]]\n- 读到高频那段 — [[2026-09-20]]\n") -> str:
    return (
        "---\nname: Zen and the Art of Motorcycle Maintenance\naliases:\n  - motorcycle\n  - 摩托车维修\n"
        "question: 这本书对 Henry 做了什么？\nupdated: 2026-09-20\n---\n\n# Zen\n\n## 答案\n\n它一直在。\n\n"
        f"## 轨迹\n\n{trail}\n## 证据\n\n- **读起来放松** · 支持 1\n"
        "  - 他说不一定，这种很多时候都是尝试出来的 — [[2026-09-20-codex-trace]]\n\n## 悬着的\n\n- 读完以后呢。\n"
    )


class TestBookPages(PeopleDirCase):
    """Book pages share the people-page rules and add a linked 轨迹."""

    def test_valid_book_page(self) -> None:
        self.assertEqual(validate_people_page(_book(), kind="books"), {"beliefs": 1, "quotes": 1})

    def test_a_book_page_needs_a_trail(self) -> None:
        with self.assertRaisesRegex(ValueError, "book page is invalid:\n- missing section ## 轨迹"):
            validate_people_page(_book().replace("## 轨迹", "## 其他"), kind="books")

    def test_every_trail_step_links_an_existing_diary_or_trace(self) -> None:
        trail = "- 没有出处的一步\n- 链到别的笔记 — [[jit-finance-denoising-seed]]\n- 链到不存在的一天 — [[2026-09-21]]\n"
        with self.assertRaises(ValueError) as caught:
            validate_people_page(_book(trail=trail), kind="books")
        message = str(caught.exception)
        self.assertEqual(message.count("without a diary or trace link"), 2)
        self.assertIn("[[2026-09-21]], which does not exist", message)

    def test_book_pages_live_in_their_own_folder(self) -> None:
        result = maintain_people_page("zen", _book(), kind="books")
        self.assertEqual(result["action"], "created")
        self.assertTrue((self.journal / "books" / "zen.md").exists())
        self.assertFalse(self.people.exists())

    def test_mentions_are_reported_per_kind(self) -> None:
        self.people.mkdir(parents=True)
        (self.people / "zheng-chen.md").write_text(_page(), encoding="utf-8")
        maintain_people_page("zen", _book(), kind="books")
        (self.journal / "2026" / "09" / "2026-09-20.md").write_text(
            "- [ ] Reading: zen and the art of motorcycle maintenance\n和郑宸聊了摩托车维修那本书\n", encoding="utf-8"
        )
        (self.trace_dir / "2026-09-20-codex-trace.md").write_text("", encoding="utf-8")
        found = pages_mentioned(date(2026, 9, 20))
        self.assertEqual([(f["kind"], f["slug"], f["mentions"]) for f in found], [("books", "zen", 2), ("people", "zheng-chen", 1)])
        self.assertEqual(
            format_pages_mentioned(found),
            [
                "People pages mentioned today (read before the analysis): zheng-chen (郑宸 ×1)",
                "Book pages mentioned today (read before the analysis): zen (Zen and the Art of Motorcycle Maintenance ×2)",
            ],
        )

    def test_unknown_kind_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "page kind must be one of people, books"):
            maintain_people_page("zen", _book(), kind="films")


DIARY_NEXT = "#diary\nHe said the edge is still in high frequency, a week later.\n"
DAY_ONE = (
    "第一次长谈。\n\n"
    "- **J1** 看重高频\n"
    "  - He said the edge is in high frequency — [[2026-09-20]]\n"
    "- **J2** loop 可以放在前面\n"
    "  - the loop can sit in front … the universe you selected — [[2026-09-20]]\n"
)
DAY_TWO = "一周后又说了一遍。\n\n- **J1** 看重高频\n  - He said the edge is still in high frequency — [[2026-09-21]]\n"


def _keyed_page(evidence: str | None = None, answer: str = "他做量化。", updated: str = "2026-09-20") -> str:
    if evidence is None:
        evidence = "- **看重高频** · J1 · 支持 0\n- **loop 可以放在前面** · J2 · 支持 0\n"
    return (
        f"---\nname: 郑宸\naliases:\n  - 郑宸\n  - Zhen\nquestion: 郑宸是谁？\nupdated: {updated}\n---\n\n"
        f"# 郑宸\n\n## 答案\n\n{answer}\n\n## 证据\n\n{evidence}\n## 悬着的\n\n- 算子库那段还没弄懂。\n"
    )


class TestPageTrail(PeopleDirCase):
    """A page keeps what changes; its trail keeps one section per day and is never rewritten."""

    def setUp(self) -> None:
        super().setUp()
        (self.journal / "2026" / "09" / "2026-09-21.md").write_text(DIARY_NEXT, encoding="utf-8")
        self.page = self.people / "zheng-chen.md"
        self.trail = self.people / "zheng-chen-trail.md"

    def _sha(self) -> str:
        return hashlib.sha256(self.page.read_bytes()).hexdigest()

    def _start(self) -> None:
        write_page_day("zheng-chen", "2026-09-20", DAY_ONE, page_text=_keyed_page())

    def test_first_day_creates_the_page_and_its_trail_and_fills_the_counts(self) -> None:
        result = write_page_day("zheng-chen", "2026-09-20", DAY_ONE, page_text=_keyed_page())
        self.assertEqual((result["trail_action"], result["page_action"]), ("created", "created"))
        self.assertIn("## 2026-09-20\n\n第一次长谈。", self.trail.read_text(encoding="utf-8"))
        page = self.page.read_text(encoding="utf-8")
        self.assertIn("- **看重高频** · J1 · 支持 1（09-20）", page)
        self.assertIn("- **loop 可以放在前面** · J2 · 支持 1（09-20）", page)

    def test_a_new_day_refreshes_counts_without_a_page_rewrite(self) -> None:
        self._start()
        before = self.page.read_text(encoding="utf-8")
        result = write_page_day("zheng-chen", "2026-09-21", DAY_TWO)
        self.assertEqual((result["trail_action"], result["page_action"]), ("added", "counts refreshed"))
        self.assertIn("- **看重高频** · J1 · 支持 2（09-20、09-21）", self.page.read_text(encoding="utf-8"))
        self.assertEqual((self.people / ".history" / "zheng-chen" / "2026-09-20.md").read_text(encoding="utf-8"), before)

    def test_more_words_on_a_counted_occasion_do_not_count_again(self) -> None:
        self._start()
        result = write_page_day("zheng-chen", "2026-09-21", DAY_TWO.replace("**J1**", "**J1+**"))
        self.assertEqual(result["page_action"], "unchanged")
        self.assertIn("· J1 · 支持 1（09-20）", self.page.read_text(encoding="utf-8"))

    def test_writing_a_day_again_replaces_only_that_section(self) -> None:
        self._start()
        write_page_day("zheng-chen", "2026-09-21", DAY_TWO)
        before = self.trail.read_text(encoding="utf-8")
        result = write_page_day("zheng-chen", "2026-09-20", DAY_ONE.replace("第一次长谈。", "第一次长谈，重写。"))
        self.assertEqual(result["trail_action"], "replaced")
        after = self.trail.read_text(encoding="utf-8")
        self.assertEqual(after, before.replace("第一次长谈。", "第一次长谈，重写。"))
        kept = self.people / ".history" / "zheng-chen" / "trail-2026-09-20.md"
        self.assertIn("第一次长谈。", kept.read_text(encoding="utf-8"))
        self.assertEqual(write_page_day("zheng-chen", "2026-09-21", DAY_TWO)["trail_action"], "no-op")

    def test_an_earlier_day_is_inserted_in_date_order(self) -> None:
        write_page_day("zheng-chen", "2026-09-21", DAY_TWO, page_text=_keyed_page(evidence="- **看重高频** · J1 · 支持 0\n"))
        late = self.trail.read_text(encoding="utf-8")
        write_page_day("zheng-chen", "2026-09-20", "- **J1** 更早的一次\n  - He said the edge is in high frequency — [[2026-09-20]]\n")
        text = self.trail.read_text(encoding="utf-8")
        self.assertLess(text.index("## 2026-09-20"), text.index("## 2026-09-21"))
        self.assertTrue(text.endswith(late[late.index("## 2026-09-21"):]))

    def test_a_trail_quote_must_be_henrys_own_words(self) -> None:
        bad = "- **J1** 看重高频\n  - He said the edge is in low frequency — [[2026-09-20]]\n"
        with self.assertRaisesRegex(ValueError, "2026-09-20 J1: quote not found verbatim"):
            write_page_day("zheng-chen", "2026-09-20", bad, page_text=_keyed_page())
        self.assertFalse(self.trail.exists())
        self.assertFalse(self.page.exists())

    def test_an_occasion_without_a_quote_needs_an_existing_source(self) -> None:
        for note, message in (
            ("只是转述", "needs a quote or a link"),
            ("转述 [[2026-09-25]]", r"cites \[\[2026-09-25\]\], which does not exist"),
        ):
            with self.subTest(note=note), self.assertRaisesRegex(ValueError, message):
                write_page_day("zheng-chen", "2026-09-20", f"- **J1** {note}\n", page_text=_keyed_page())
        linked = "- **J1** 转述 [[2026-09-20]]\n- **J2** 转述 [[2026-09-20-codex-trace]]\n"
        write_page_day("zheng-chen", "2026-09-20", linked, page_text=_keyed_page())

    def test_an_id_the_page_does_not_list_is_refused(self) -> None:
        self._start()
        new = "- **J9** 新的判断\n  - He said the edge is still in high frequency — [[2026-09-21]]\n"
        with self.assertRaisesRegex(ValueError, "J9 is used in the trail but is on no belief of the page"):
            write_page_day("zheng-chen", "2026-09-21", new)
        self.assertNotIn("2026-09-21", self.trail.read_text(encoding="utf-8"))
        page = _keyed_page(evidence="- **看重高频** · J1 · 支持 0\n- **loop** · J2 · 支持 0\n- **新的判断** · J9 · 支持 0\n")
        result = write_page_day("zheng-chen", "2026-09-21", new, page_text=page, base_sha256=self._sha())
        self.assertEqual(result["page_action"], "rewritten")
        self.assertIn("- **新的判断** · J9 · 支持 1（09-21）", self.page.read_text(encoding="utf-8"))

    def test_beliefs_can_be_merged_on_the_page_without_touching_the_trail(self) -> None:
        self._start()
        trail = self.trail.read_text(encoding="utf-8")
        merged = _keyed_page(evidence="- **他怎么看 edge 和 loop** · J1 J2 · 支持 0\n")
        result = maintain_people_page("zheng-chen", merged, base_sha256=self._sha())
        self.assertEqual(result["beliefs"], 1)
        self.assertIn("· J1 J2 · 支持 2（09-20）", self.page.read_text(encoding="utf-8"))
        self.assertEqual(self.trail.read_text(encoding="utf-8"), trail)

    def test_a_page_with_a_trail_is_checked_against_it(self) -> None:
        self._start()
        cases = (
            ("- **看重高频** · J1 · 支持 0\n", "J2 is used in the trail but is on no belief"),
            ("- **看重高频** · J1 J2 · 支持 0\n- **又一条** · J2 · 支持 0\n", "J2 is listed on two beliefs"),
            ("- **看重高频** · J1 J2 · 支持 0\n- **没出现过** · J7 · 支持 0\n", "no counted occasion in the trail for J7"),
            ("- **看重高频** · J1 J2 · 支持 0\n- **没有编号** · 支持 1\n", "belief without an id"),
            (
                "- **看重高频** · J1 J2 · 支持 0\n  - 他说不一定，这种很多时候都是尝试出来的 — [[2026-09-20-codex-trace]] 16:17\n",
                "quote is not in the trail under J1 J2",
            ),
        )
        for evidence, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                maintain_people_page("zheng-chen", _keyed_page(evidence=evidence), base_sha256=self._sha())
        copied = "- **看重高频** · J1 J2 · 支持 0\n  - He said the edge is in high frequency — [[2026-09-20]]\n"
        self.assertEqual(maintain_people_page("zheng-chen", _keyed_page(evidence=copied), base_sha256=self._sha())["quotes"], 1)

    def test_a_whole_page_rewrite_of_a_page_with_a_trail_says_what_to_do_instead(self) -> None:
        self._start()
        with self.assertRaises(ValueError) as caught:
            maintain_people_page("zheng-chen", _page(), base_sha256=self._sha())
        message = str(caught.exception)
        self.assertIn("belief without an id", message)
        self.assertIn("This page has a trail. Write the day with --day and --day-file", message)

    def test_a_page_with_a_trail_must_fit_in_one_read(self) -> None:
        self._start()
        long_page = _keyed_page(answer="长" * 9000)
        with self.assertRaisesRegex(ValueError, "over the one-read budget of 24,000"):
            maintain_people_page("zheng-chen", long_page, base_sha256=self._sha())

    def test_a_whole_page_needs_splitting_before_it_takes_a_day(self) -> None:
        maintain_people_page("zheng-chen", _page())
        with self.assertRaisesRegex(ValueError, "has no trail yet; split it first with migrate-page-trail"):
            write_page_day("zheng-chen", "2026-09-20", DAY_ONE)

    def test_a_page_rewrite_with_a_day_needs_the_hash_that_was_read(self) -> None:
        self._start()
        with self.assertRaisesRegex(ValueError, "pass --base-sha256"):
            write_page_day("zheng-chen", "2026-09-21", DAY_TWO, page_text=_keyed_page())
        with self.assertRaisesRegex(ValueError, "changed since it was read"):
            write_page_day("zheng-chen", "2026-09-21", DAY_TWO, page_text=_keyed_page(), base_sha256="0" * 64)
        self.assertNotIn("2026-09-21", self.trail.read_text(encoding="utf-8"))

    def test_dry_run_writes_nothing(self) -> None:
        result = write_page_day("zheng-chen", "2026-09-20", DAY_ONE, page_text=_keyed_page(), dry_run=True)
        self.assertEqual(result["trail_action"], "created")
        self.assertFalse(self.people.exists())

    def test_the_heading_of_a_day_file_must_match_the_day(self) -> None:
        with self.assertRaisesRegex(ValueError, "headed 2026-09-21, not 2026-09-20"):
            write_page_day("zheng-chen", "2026-09-20", "## 2026-09-21\n\n" + DAY_ONE, page_text=_keyed_page())
        write_page_day("zheng-chen", "2026-09-20", "## 2026-09-20\n\n" + DAY_ONE, page_text=_keyed_page())
        self.assertEqual(self.trail.read_text(encoding="utf-8").count("## 2026-09-20"), 1)

    def test_the_trail_is_not_a_page_and_the_read_plan_points_at_its_last_days(self) -> None:
        self._start()
        write_page_day("zheng-chen", "2026-09-21", DAY_TWO)
        (self.journal / "2026" / "09" / "2026-09-21.md").write_text("今天又和郑宸聊了。" + DIARY_NEXT, encoding="utf-8")
        found = pages_mentioned(date(2026, 9, 21))
        self.assertEqual([item["slug"] for item in found], ["zheng-chen"])
        lines = format_pages_mentioned(found)
        self.assertEqual(len(lines), 2)
        self.assertRegex(lines[1], r"^- zheng-chen has a trail: after the page, read .*zheng-chen-trail\.md lines \d+-end \(last 2 of 2 days, [\d,]+ bytes\)$")
        with patch.object(copilot_module, "ROOT", self.journal.parent):
            self.assertNotIn(self.trail, read_budget_paths(date(2026, 9, 21)))

    def test_a_slug_cannot_take_the_trail_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not end in -trail"):
            maintain_people_page("zheng-chen-trail", _page())


class TestMigrateToTrail(PeopleDirCase):
    """Splitting a page that was rewritten whole: nothing may be dropped."""

    def setUp(self) -> None:
        super().setUp()
        (self.journal / "2026" / "09" / "2026-09-21.md").write_text(DIARY_NEXT, encoding="utf-8")
        self.old = (
            "---\nname: 郑宸\naliases:\n  - 郑宸\nquestion: 郑宸是谁？\nupdated: 2026-09-21\n---\n\n# 郑宸\n\n"
            "**问题**：郑宸是谁？\n\n## 答案\n\n2026-09-20 新建。\n\n他做量化。\n\n"
            "[[2026-09-20]] 第一次长谈。\n\n课后又补了一句。\n\n[[2026-09-21]] 一周后。\n\n现状：还在聊。\n\n"
            "## 证据\n\n支持次数是独立出现的场合数。\n\n"
            "- **看重高频** · 支持 2（09-20 第一次，09-21 又说）\n"
            "  - He said the edge is in high frequency — [[2026-09-20]]\n"
            "  - He said the edge is still in high frequency, a week later. — [[2026-09-21]]\n"
            "- **loop 可以放在前面** · 支持 1（09-20；09-21 那句是补充）\n"
            "  - the loop can sit in front — [[2026-09-20]]\n"
            "  - 他说不一定，这种很多时候都是尝试出来的 — [[2026-09-20-codex-trace]] 16:17\n\n"
            "## 悬着的\n\n- 算子库那段还没弄懂。\n"
        )
        self.plan = {"paragraphs": {"1": "preamble", "2": "page", "4": "2026-09-20", "6": "page"}}

    def test_every_line_survives_and_counts_come_out_the_same(self) -> None:
        plan = dict(self.plan, occasions={"J2": {"count": ["2026-09-20"]}})
        result = migrate_page_to_trail("zheng-chen", self.old, plan, "2026-10-04")
        self.assertEqual((result["lost_lines"], result["mismatches"], result["problems"]), ([], [], []))
        page, trail = str(result["page"]), str(result["trail"])
        self.assertIn("## 答案\n\n他做量化。\n\n现状：还在聊。\n\n## 证据\n\n支持次数是独立出现的场合数。", page)
        self.assertIn("- **看重高频** · J1 · 支持 2（09-20、09-21）\n- **loop 可以放在前面** · J2 · 支持 1（09-20）", page)
        self.assertIn("2026-09-20 新建。\n\n## 拆页前的判断清单", trail)
        self.assertIn("J1\n- **看重高频** · 支持 2（09-20 第一次，09-21 又说）\nJ2\n", trail)
        self.assertIn(
            "## 2026-09-20\n\n[[2026-09-20]] 第一次长谈。\n\n课后又补了一句。\n\n"
            "- **J1** 看重高频\n  - He said the edge is in high frequency — [[2026-09-20]]\n"
            "- **J2** loop 可以放在前面\n  - the loop can sit in front — [[2026-09-20]]\n"
            "  - 他说不一定，这种很多时候都是尝试出来的 — [[2026-09-20-codex-trace]] 16:17\n",
            trail,
        )
        self.assertIn("## 2026-09-21\n\n[[2026-09-21]] 一周后。\n\n- **J1** 看重高频\n", trail)
        self.assertEqual(validate_people_page(page, trail=trail)["trail_quotes"], 4)

    def test_a_count_the_note_does_not_explain_is_reported(self) -> None:
        old = self.old.replace("支持 1（09-20；09-21 那句是补充）", "支持 1（两次都算在一起）")
        result = migrate_page_to_trail("zheng-chen", old, self.plan, "2026-10-04")
        self.assertEqual(result["mismatches"], [])
        # A note that names a day which was not a separate occasion needs the plan to say so.
        mismatch = migrate_page_to_trail("zheng-chen", self.old, self.plan, "2026-10-04")["mismatches"]
        self.assertEqual([(m["id"], m["stated"], m["counted"]) for m in mismatch], [("J2", 1, ["2026-09-20", "2026-09-21"])])
        plan = dict(self.plan, occasions={"J2": {"count": ["2026-09-20"]}})
        old = self.old.replace("支持 2（09-20 第一次，09-21 又说）", "支持 3（还有一次没写日期）")
        mismatch = migrate_page_to_trail("zheng-chen", old, plan, "2026-10-04")["mismatches"]
        self.assertEqual([(m["id"], m["stated"], m["counted"]) for m in mismatch], [("J1", 3, ["2026-09-20", "2026-09-21"])])

    def test_a_named_day_without_a_quote_becomes_a_linked_occasion(self) -> None:
        old = self.old.replace("支持 1（09-20；09-21 那句是补充）", "支持 2（09-20，09-21 又提了一次）")
        result = migrate_page_to_trail("zheng-chen", old, self.plan, "2026-10-04")
        self.assertEqual((result["mismatches"], result["problems"]), ([], []))
        self.assertIn("- **J2** loop 可以放在前面（拆页时按旧页的支持说明记这一次，没有摘原话）[[2026-09-21]]", str(result["trail"]))
        self.assertIn("· J2 · 支持 2（09-20、09-21）", str(result["page"]))

    def test_the_plan_can_count_two_occasions_on_one_day(self) -> None:
        old = self.old.replace("支持 2（09-20 第一次，09-21 又说）", "支持 3（09-20 课上和课后各一次，09-21 又说）")
        plan = dict(self.plan, occasions={
            "J1": {"count": ["2026-09-20", "2026-09-20", "2026-09-21"]},
            "J2": {"count": ["2026-09-20"]},
        })
        result = migrate_page_to_trail("zheng-chen", old, plan, "2026-10-04")
        self.assertEqual((result["lost_lines"], result["mismatches"], result["problems"]), ([], [], []))
        self.assertIn("- **J1** 看重高频（拆页时按旧页的支持说明记同一天的另一次，没有摘原话）[[2026-09-20]]", str(result["trail"]))
        self.assertIn("· J1 · 支持 3（09-20、09-21）", str(result["page"]))

    def test_undated_paragraphs_need_a_home(self) -> None:
        with self.assertRaisesRegex(ValueError, "must place these answer paragraphs.*\n- 1: 2026-09-20 新建。\n- 2: 他做量化。"):
            migrate_page_to_trail("zheng-chen", self.old, {}, "2026-10-04")


if __name__ == "__main__":
    unittest.main()
