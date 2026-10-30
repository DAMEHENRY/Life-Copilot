"""Tests for the Colour of the Day brief parsing and diary placement."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.copilot import (
    COLOUR_SECTION,
    replace_journal_copilot_section,
    split_colour_brief,
    upsert_colour_image,
)

IMG = "![Colour of the Day](../../paintings/2026/01/2026-01-01-colour.png)"


class SplitBriefTest(unittest.TestCase):
    def test_reading_and_prompt(self):
        reading, prompt = split_colour_brief("## Reading\n灰里透一点暖。\n\n## Prompt\nA grey field.\n")
        self.assertEqual(reading, "灰里透一点暖。")
        self.assertEqual(prompt, "A grey field.")

    def test_prompt_only(self):
        self.assertEqual(split_colour_brief("## Prompt\nA grey field."), ("", "A grey field."))

    def test_missing_prompt(self):
        with self.assertRaises(ValueError):
            split_colour_brief("## Reading\nsomething")
        with self.assertRaises(ValueError):
            split_colour_brief("## Prompt\n\n")


class ColourImageTest(unittest.TestCase):
    DIARY = "## 📸 Daily Moment\n> x\n\n## 💬 From Kai\n\n- [[t]]\n\n## What Life Copilot Said\n\nhi\n"

    def test_sits_between_heading_and_reply(self):
        out = upsert_colour_image(self.DIARY, IMG)
        self.assertIn("## What Life Copilot Said\n\n" + IMG + "\n\nhi\n", out)

    def test_repainting_replaces_once(self):
        once = upsert_colour_image(self.DIARY, IMG.replace("01-01", "01-02"))
        twice = upsert_colour_image(once, IMG)
        self.assertEqual(twice.count("![Colour of the Day]"), 1)
        self.assertIn(IMG, twice)

    def test_moves_old_standalone_section(self):
        old = self.DIARY.replace("## 💬 From Kai", f"{COLOUR_SECTION}\n\n{IMG}\n\n## 💬 From Kai")
        out = upsert_colour_image(old, IMG)
        self.assertNotIn(COLOUR_SECTION, out)
        self.assertIn("## 📸 Daily Moment\n> x\n\n## 💬 From Kai", out)
        self.assertEqual(out.count(IMG), 1)

    def test_needs_the_reply_first(self):
        with self.assertRaises(ValueError):
            upsert_colour_image("## 💬 From Kai\n", IMG)


class RewriteKeepsPaintingTest(unittest.TestCase):
    def test_rewritten_reply_keeps_painting(self):
        painted = upsert_colour_image("## What Life Copilot Said\n\nold\n\n## Next\n", IMG)
        out = replace_journal_copilot_section(painted, "new reply")
        self.assertIn(f"## What Life Copilot Said\n\n{IMG}\n\nnew reply\n\n## Next", out)
        self.assertNotIn("old", out)

    def test_unpainted_reply_unchanged(self):
        out = replace_journal_copilot_section("## What Life Copilot Said\n\nold\n", "new")
        self.assertEqual(out, "## What Life Copilot Said\n\nnew\n")


if __name__ == "__main__":
    unittest.main()
