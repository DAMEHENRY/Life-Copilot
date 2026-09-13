"""Tests for the local recall tool's provenance labels and hit merging (no model download needed)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("recall", ROOT / "tools" / "recall" / "recall.py")
recall = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(recall)


DIARY = """#diary
#  📅  2026-01-02
## 🧭 Daily Suggestion

> Generated from [[2026-01-01]] diary analysis.

Suggestion text for today.
## 💭 Thoughts & Reflections
I wrote this myself.

> [!info] 对话转写
> 这段内容来自 Henry 与 Life Copilot 的直接对话，由 Life Copilot 整理转写；不是 Henry 手写原文。

A transcribed retelling.


Back to my own words.

### 对话补记

> [!info] 对话转写
> capture-id: chat-capture-2026-01-02
> 这段内容来自 Henry 与 Life Copilot 的直接对话，由 Life Copilot 合并整理。

### A capture subsection

Captured paragraph.
## 💬 From Kai

- [[2026-01-02-codex-trace]]：Codex conversations.
## What Life Copilot Said

```text
code should be skipped
```
Relational response.
"""

TRACE = """---
date: 2026-01-02
source: codex
---

# 2026-01-02 Codex Trace

### Session one

[1/2/26 9:00 AM] Henry: hello there
"""


def labels(rel: str, text: str) -> dict:
    return {content: kind for _, kind, _, content in recall.labeled_lines(rel, text)}


def test_diary_sections_and_transcripts_carry_provenance() -> None:
    found = labels("journal/2026/01/2026-01-02.md", DIARY)

    assert found["Suggestion text for today."] == "copilot"
    assert found["I wrote this myself."] == "handwritten"
    assert found["A transcribed retelling."] == "transcribed"
    assert found["Back to my own words."] == "handwritten"
    assert found["Captured paragraph."] == "transcribed"
    assert found["Relational response."] == "copilot"
    assert not any("Codex conversations" in line for line in found)
    assert not any("code should be skipped" in line for line in found)
    assert not any("Generated from" in line for line in found)


def test_trace_lines_are_labeled_as_trace_without_frontmatter() -> None:
    assert labels("journal/ai-conversations/2026/01/2026-01-02-codex-trace.md", TRACE) == {
        "[1/2/26 9:00 AM] Henry: hello there": "trace",
    }


def test_only_diaries_and_traces_are_sources() -> None:
    assert recall.DIARY_RE.match("journal/2026/01/2026-01-02.md")
    assert not recall.DIARY_RE.match("journal/memory.md")
    assert not recall.DIARY_RE.match("journal/disconfirmation/2026-01-02-sheet.md")


def test_merge_hits_combines_overlapping_chunks_from_one_file() -> None:
    chunks = [
        {"path": "a.md", "date": "2026-01-01", "kind": "handwritten", "section": "", "line_start": 1, "line_end": 3, "text": "x"},
        {"path": "a.md", "date": "2026-01-01", "kind": "handwritten", "section": "", "line_start": 3, "line_end": 5, "text": "y"},
        {"path": "b.md", "date": "2026-01-02", "kind": "trace", "section": "", "line_start": 1, "line_end": 2, "text": "z"},
    ]
    hits = recall.merge_hits([0, 1, 2], np.array([0.9, 0.8, 0.7]), chunks, k=5)

    assert [(h["path"], h["line_start"], h["line_end"]) for h in hits] == [("a.md", 1, 5), ("b.md", 1, 2)]
    assert hits[0]["score"] == 0.9
