# Life Copilot v4.7 RFC

> Status: in progress. Henry approved the design and its first four steps on 2026-10-04; each step is marked in Migration as it lands.
> Date: 2026-10-04
> Extends: [[life-copilot-v4.5-rfc]], [[life-copilot-v4.6-rfc]]

## Problem

**A page that is rewritten whole carries its past forward, so it only grows.** v4.5 named this for memory entries: updates carry the old text forward, so exactly the updated entries grow. People pages inherited the mechanism. The largest page went from 5 KB on 2026-09-22 to 66 KB on 2026-10-04 over seventeen rewrites. The answer became a daily record: 11 of its 20 paragraphs open with a date and hold 19 of its 31 KB. Beliefs went from 11 to 62 (40 of them supported once), quotes from 16 to 197, open questions from 3 to 28, and none was ever closed. The page now takes three reads every night, and `.history/` keeps a full copy for every rewrite.

**The only way to make such a page smaller is to lose content.** On 2026-10-03 another model rewrote the page at 39 KB. It followed the rule (an answer rewritten as a whole) and dropped a timetable, a timing comparison and most of the daily record, because the page was the only place they lived. Henry's requirement on 2026-10-04: the mechanism may change, the content may not shrink.

The two problems are one. Text that only accumulates (what happened on a day, what Henry said) is kept in a file whose only write is "rewrite all of it".

## Decision

### A page and its trail

Split by lifecycle.

- **The page** (`journal/people/{slug}.md`) holds what changes: the standing answer, the beliefs with their support counts, the open questions. It is rewritten when the understanding changes, and it must fit in one read (`READ_BUDGET_BYTES`).
- **The trail** (`journal/people/{slug}-trail.md`) holds what accumulates: one `## YYYY-MM-DD` section per day the person appears. A section is that day's account plus that day's quotes. It is written once. Running the same day again replaces only that section, and the replaced text goes to `.history/`. No other section is touched; a correction is a new section.

A trail section:

```markdown
## 2026-09-21

A week later he said it again. (A free account of the day. Copilot's readings are marked as such.)

- **J41** 一周后又说了一次
  - He said the edge is still in high frequency. — [[2026-09-21]]
- **J12+** 补了 09-20 那次长谈里的一句
  - 他说不一定，这种很多时候都是尝试出来的 — [[2026-09-20-codex-trace]] 16:17
```

`- **J41** …` is one independent occasion for belief J41. `- **J12+** …` adds words about an occasion already counted and does not count again. Quotes sit under the occasion they belong to and are checked the way page quotes are today: Henry's own words, verbatim, in the diary or trace they cite. An occasion without a quote must link a diary or trace that exists.

A belief on the page:

```markdown
- **看重高频** · J41 · 支持 4（09-16、09-20、09-21、09-28）
  - He said the edge is still in high frequency. — [[2026-09-21]]
```

The number and the dates are filled in by the script from the trail. A line may list several ids (`· J31 J44 ·`), so fine-grained beliefs can be merged into one pattern on the page while every record stays in the trail. Quotes on the page are optional and must be copies of trail quotes.

### What the script guarantees

1. A day's write can change that day's section and nothing else in the trail.
2. Every quote in the trail is Henry's own words, verbatim, in its cited source.
3. Every id used in the trail is listed on exactly one belief line of the page; the count on that line equals the occasions in the trail.
4. Every quote on the page is also in the trail, so rewriting the page cannot lose anything.
5. A page with a trail never exceeds one read. Over the budget, `maintain-page` refuses and says what can move.
6. Migration is line-exact: every non-empty line of the old page must appear in the new page or the trail, or nothing is written.

### Reading and writing

- **Read**: the page in full, then the last three days of its trail. `writeback-ai-day` and `check-read-budget --date` print the line range. Older days are found by date or by belief id (`J41`); the diary stays the authority, as before.
- **Write, most nights**: one trail section. The page's counts refresh by themselves.
- **Write, when the understanding changes**: the trail section plus a page rewrite, with the same compare-and-swap and `.history/` as today.
- **Open questions**: a question that is answered leaves the page with the answer written into that day's trail section.

Pages without a trail keep today's shape and checks. A page gets a trail when it no longer fits in one read, or when Henry asks.

### Not changed

The diary and traces remain the source of truth. Book pages keep their in-page `## 轨迹` for now. Memory entries are untouched; `memory.md` has the same growth pattern and is a separate question.

## Interfaces

| Command | Change |
|---|---|
| `maintain-page --slug S --day D --day-file F [--input-file P --base-sha256 H] [--dry-run]` | new: write one trail section; rewrite the page too if given, else refresh its counts |
| `maintain-page --slug S --input-file P --base-sha256 H` | on a page with a trail: fills counts and dates, checks ids, copied quotes and the one-read budget |
| `migrate-page-trail --slug S --plan F [--out-dir DIR] [--dry-run]` | new: split an existing page into page and trail, line-exact |
| `writeback-ai-day`, `check-read-budget --date` | for a mentioned page with a trail, also print the trail's line range for its last three days |

## Rule ownership

- **`journal/people/00-index.md`**: the two shapes and the nightly procedure. Not in git; edited when the pilot page is migrated.
- **AGENTS.md** (L2, requested by Henry): the trail in the file-map row for people pages, the `--day` form under structured writeback, and the read rule (page in full, trail by its last days).
- **prompts/diary-mode.md** (L0 candidate): the Completion Contract's page step points at `00-index.md` for how to maintain a page, which shortens it. Promoted through the evolution policy.

## Migration

Each step is one commit. If work stops between two steps, Diary Mode still runs.

1. **Code and tests**: trail sections, the `--day` write, count refresh, the read-plan line, `migrate-page-trail`. No page has a trail yet, so behaviour does not change.
2. **Pilot**: migrate the largest page with a dry run first. Henry reads the result before it is applied. `00-index.md` describes both shapes from this step on.
3. **AGENTS.md**: manual L2 commit.
4. **diary-mode.md**: candidate, review, `promote-system-rule`.
5. **Observe for a week**, then migrate the next-largest page and decide on the rest; book pages after that.

## Pilot dry run (2026-10-04)

The largest page, split into scratch copies. The page in the vault was not touched.

| | Before | After |
|---|---|---|
| Page | 67,891 bytes, three reads | 18,072 bytes, one read |
| Trail | none | 67,076 bytes, 18 day sections |
| Nightly read | 67,891 bytes | 27,765 bytes: the page plus the trail's last three days |

No line was lost. All 197 quotes are in the trail, and all 62 support counts equal the old page's (115 occasions). Forty-nine counts followed from the dates in the old support notes. Thirteen needed a decision in the plan file: the note named a day that was not a separate occasion, or one day held more than one.

On the copies, writing 2026-10-03 a second time replaced that section and left every earlier day byte-identical, and a new day raised one belief's count with no page rewrite.

The split is mechanical. It does not merge the 40 beliefs that rest on one occasion, and it closes no open question; those are ordinary page rewrites afterwards, and with ids they lose nothing.

## Acceptance

- The pilot migration passes the line-exact check, and the migrated page fits in one read.
- After a week of nightly runs: no trail section other than the day being written has changed; the page is still within one read; no belief count was typed by hand.
- A second analysis of the same day (as on 2026-10-03) replaces one trail section and leaves earlier days byte-identical.
- Tests pass, and prompts/diary-mode.md does not grow.
