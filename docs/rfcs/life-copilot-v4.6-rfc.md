# Life Copilot v4.6 RFC

> Status: in progress. Code, AGENTS.md and the first page landed 2026-09-29; the prompt steps wait for the v4.5 observation windows to close (diary-mode 2026-09-29, chat-mode 2026-09-30)
> Date: 2026-09-29
> Extends: [[life-copilot-v4.5-rfc]]

## Problem

**A book read over months has no home.** On 2026-09-29, a word near the end of *Zen and the Art of Motorcycle Maintenance* brought back the night Henry first opened it. Answering "what has this book been in my life" meant reading more than forty diaries one by one: the thread was split across the Habits reading line, merged captures, traces and Copilot's responses. The one sentence that dated the first reading lived only in a trace. The conversation that recommended the book is not in any archive. On 2026-09-18 Kai had already searched for the same records; nothing kept that search, so it was repeated from scratch.

This is the same gap people pages closed for a person: cumulative understanding cut by date into fragments, visible only to whoever searches.

## Decision

### Book pages

A book page is a people page for a book, plus a trail.

- **Where**: `journal/books/{slug}.md`, git-ignored with the rest of `journal/`. Shape and rules live in `journal/books/00-index.md`.
- **Shape**: the people-page shape — YAML (`name`, `aliases`, `question`, `updated`), the answer rewritten as a whole, evidence as beliefs with support counts and verbatim quotes from Henry's own words, open questions — plus `## 轨迹`: the reading path in date order, one step per line, each step linking at least one diary or trace that exists. Steps may paraphrase; beliefs may not.
- **Read**: the day's mentioned pages now cover both kinds. The Habits reading line counts as Henry's own words, so logging a book surfaces its page that day without any new habit.
- **Write**: `maintain-page --kind books`, with the same dry-run, compare-and-swap and `.history/` as people pages.
- **Which books**: the ones Henry asks for, or one where Henry's own words about its content (not just the title on the reading line) appear on at least three separate days — proposed at a Diary Mode close, created on his yes.

The first page is *Zen and the Art of Motorcycle Maintenance*: 11 beliefs, 29 quotes, 32 trail steps.

## Interfaces

| Command | Change |
|---|---|
| `maintain-page --kind {people,books}` | new flag, default `people` |
| `writeback-ai-day`, `check-read-budget --date` | also list mentioned book pages, on their own line |

## Rule ownership

- **AGENTS.md** (L2, requested by Henry): a file-map row, the read rule next to the people-page one, the `--kind books` note under structured writeback.
- **prompts/diary-mode.md** (L0 candidate, after 2026-09-29): read mentioned book pages alongside people pages; maintain them in the same Completion Contract step; propose a new page when a book crosses the three-day threshold.
- **prompts/chat-mode.md** (L0 candidate, after 2026-09-30): none needed beyond AGENTS.md unless observation shows Chat missing pages.

## Migration

1. Code and tests: page kinds in `scripts/copilot.py`, book tests in `tests/test_people_pages.py`. Done.
2. `journal/books/00-index.md` and the first page. Done.
3. AGENTS.md. Done.
4. diary-mode.md candidate, promoted through the evolution policy once its v4.5 window has closed.
