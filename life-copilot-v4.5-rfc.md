# Life Copilot v4.5 RFC

> Status: in progress — migration steps 1–4 landed on 2026-09-22
> Date: 2026-09-21
> Extends: [[life-copilot-v4.4-rfc]]

## Problem

**Reads can lose content silently.** One tool output reaches the model whole only up to a per-agent cap. Claude Code's default is 30,000, and measured on this machine it behaves as bytes, so Chinese text hits it near 10,000 characters. Over the cap the harness says so and saves the full output to a file, but an agent can answer that with a lossy filter — `cut`, a guessed line range — and lose content with no trace anyone else can see. On 2026-09-20 hot memory was read exactly that way: every Active entry was cut at 200 bytes and the Stable Profile was skipped by a line-range guess, so a standing preference was missed. The write side already refuses silent loss (the trace rewrite guard, web-sync counts, checksummed OpenClaw batches); the read side had no receipt.

**Understanding of a person has no home.** Active Hypotheses is a 30-day window, Canonical keeps validated general patterns, and the Life Board keeps projects. Cumulative understanding of a person or a relationship fits none of them, so it is cut by date into fragments spread over the window, the archive and Canonical — a single relationship can span dozens. The agent sees only the fragments still in the window unless it searches the archive.

**Updated entries never expire and keep growing.** `replace-active` stamps the maintenance date and `compact-memory` expires entries by that date, so an entry that keeps being updated stays hot indefinitely. Updates carry the old text forward (median 97% verbatim across traced updates), so exactly those entries grow. The worst case is a behavioural rule kept as an 1,800-character memory entry, with the rule itself about 700 characters in.

## Decision

### Read budget

`READ_CAP_BYTES = 30_000` is the largest output an agent can count on receiving whole; `READ_BUDGET_BYTES = 24_000` leaves a fifth of headroom. `check-read-budget [--date]` lists every must-read unit — AGENTS.md, CLAUDE.md, the prompts, life-board.md, memory.md and, with a date, that day's diary, traces and mentioned people pages — and gives a line-range plan for anything over budget. `writeback-ai-day` prints the units that are not ok before the journal path, so every Diary Mode run starts with its reading plan.

A test keeps tracked must-read files within budget. Files already over it (prompts/diary-mode.md) are baselined: they may shrink but not grow, and leave the baseline once back under budget.

Rule: never base a judgment on a lossy filter. When an output is persisted, read the saved file in the planned ranges.

Harness: `bashOutputMaxChars = 128000` in user settings (applied 2026-09-21). The planning budget stays at 30,000 bytes until every agent that runs Diary Mode is known to accept more; Codex's `tool_output_token_limit` is unverified.

### People pages

Borrowed from Hindsight's mental models, knowledge pages and observations: a standing answer to a question, rewritten from the evidence, with beliefs that carry verbatim quotes and a proof count. Not borrowed: its database, extraction-on-write and background rewriting — the diary stays the source of truth.

- **Where**: `journal/people/{slug}.md`, git-ignored. The shape and rules live in `journal/people/00-index.md`.
- **Shape**: YAML (`name`, `aliases`, `question`, `updated`); the question; an answer rewritten as a whole on every update; evidence as beliefs, each with a support count (independent occasions) and verbatim dated quotes; open questions.
- **Authority**: derived, never authoritative. Quotes are checked against the source before they are written.
- **Read**: pages whose aliases appear in the day's diary or traces. `writeback-ai-day` lists them and the read plan includes them.
- **Write**: `maintain-page`, with dry-run, compare-and-swap on the hash of the version that was read (so a hand edit is never overwritten), and the previous version copied to `journal/people/.history/{slug}/`.
- **Promotion**: an Active entry updated a third time is answering a standing question. It becomes a page (a person or a topic) or, if it is a behavioural rule, moves into the prompt layer.

### Closing greetings

The style rule and the ledger of used material move from memory to `journal/closing-greetings.md`, one standing-answer page read by both Chat Mode's bedtime close and Diary Mode's final response. The `response-style` memory entry is archived with a pointer.

### Kept as is

Active entries stay as rich as they are; there is no length cap. The 30-day window and the monthly `compact-memory` job are unchanged.

## Interfaces

| Command | Change |
|---|---|
| `check-read-budget [--date] [--json]` | new; in the working tree since 2026-09-21, uncommitted |
| `writeback-ai-day` | prints the read plan, and later the mentioned pages, before the journal path |
| `maintain-page --slug S --input-file F [--base-sha256 H] [--dry-run]` | new |

## Rule ownership

- **AGENTS.md** (L2, requested by Henry): a file-map row for people pages; `check-read-budget` and `maintain-page` under structured writeback; the read rule under general guardrails; version header.
- **prompts/diary-mode.md** (L0 candidate): read memory.md in full following the plan, Stable Profile always; add mentioned people pages to context; a page-maintenance step in the Completion Contract after memory maintenance; the third-update promotion rule; a pointer to `journal/closing-greetings.md`; a read receipt in the final execution note. Room comes from replacing the importer-details bullet in the From Kai evidence section with a pointer to AGENTS.md, which already states it.
- **prompts/chat-mode.md** (L0 candidate, a later closure): the bedtime close reads `journal/closing-greetings.md`.

## Migration

Each step is one commit. If work stops between any two steps, Diary Mode still runs.

1. **Preconditions**: the 2026-09-21 closeout is written; `git status` shows only the read-budget change; tests pass.
2. **Read budget**: commit and push `scripts/copilot.py` and `tests/test_read_budget.py`.
3. **People-page code**: `maintain-page`, alias matching (ASCII on word boundaries, Chinese as substrings, aliases shorter than two Chinese or three ASCII characters rejected), `.history`, pages in the `writeback-ai-day` summary and the read plan, tests. No prompt reads pages yet, so behaviour changes by one printed line.
4. **AGENTS.md**: manual L2 commit.
5. **diary-mode.md**: candidate manifest, review against the 13 golden cases and one recent trace, `promote-system-rule` (own commit, before snapshot, ledger).
6. **Memory migration**: create `journal/closing-greetings.md` from the `response-style` entry and archive the entry; archive the pilot person's memory entry with a pointer to the page; list the other re-dated entries for Henry to decide.
7. **chat-mode.md**: candidate at the next closure.
8. **Observe for a week**, then decide on further pages; pages about family need Henry's review before they are written.

## Acceptance

- Every Diary Mode closeout states which required sources were read fully and which in parts.
- The pilot page is rewritten, not appended, when its person appears; new quotes match the source verbatim; counts match independent occasions; the previous version exists under `.history`.
- No memory entry is updated a third time without being promoted.
- Tests pass, and prompts/diary-mode.md does not grow past its baseline.
