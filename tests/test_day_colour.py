"""Tests for the Colour of the Day brief parsing and diary placement."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.copilot import COLOUR_SECTION, split_colour_brief, upsert_colour_section

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


class UpsertSectionTest(unittest.TestCase):
    DIARY = "## 📸 Daily Moment\n> x\n\n## 💬 From Kai\n\n- [[t]]\n\n## What Life Copilot Said\n\nhi\n"

    def test_inserts_before_from_kai(self):
        out = upsert_colour_section(self.DIARY, IMG)
        self.assertLess(out.index(COLOUR_SECTION), out.index("## 💬 From Kai"))
        self.assertGreater(out.index(COLOUR_SECTION), out.index("## 📸 Daily Moment"))
        self.assertIn(IMG, out)

    def test_replaces_existing_once(self):
        once = upsert_colour_section(self.DIARY, "old")
        twice = upsert_colour_section(once, IMG)
        self.assertEqual(twice.count(COLOUR_SECTION), 1)
        self.assertNotIn("old", twice)
        self.assertIn("## 💬 From Kai\n\n- [[t]]", twice)

    def test_falls_back_to_copilot_section(self):
        out = upsert_colour_section("## What Life Copilot Said\n\nhi\n", IMG)
        self.assertTrue(out.startswith(COLOUR_SECTION))


if __name__ == "__main__":
    unittest.main()
