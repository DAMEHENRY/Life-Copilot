# Life Copilot

> Version: v4.3 (2026-06-04)
> Runtime: Claude Code / Codex + Obsidian + local files
> Design note: [[life-copilot-v4.3-rfc]]

Life Copilot is Henry's local personal operating system. It is not a task app, not a scheduler, and not a database. It is a small set of files and scripts that help an AI assistant read the right local evidence, preserve provenance, and suggest the smallest useful next step.

## Design Philosophy

> **Do as much as needed, as little as possible.**

This is the top-level rule for v4.3. The system should do enough to preserve evidence, protect writeback boundaries, and keep active work visible. It should avoid adding rules, files, scripts, or modes just because they might be useful someday.

In practice:

- Keep the evidence layer strict.
- Keep the operating layer light.
- Prefer one clear input route over many clever routes.
- Prefer a conversational projection over a generated schedule unless legacy Quant structure is explicitly needed.
- Let parked ideas stay in `seeds/` instead of forcing them into active projects.

---

## 1. Current Shape

The current system is organized around five surfaces:

| Surface | Path | Role |
|---|---|---|
| Rules | `AGENTS.md` | Runtime instructions for AI agents |
| Active board | `life-board.md` | What Henry is currently working on |
| Diary + memory | `journal/` | Evidence, traces, memory, and daily analysis |
| Seeds | `seeds/` | Valuable ideas that are not active projects yet |
| Scripts | `scripts/copilot.py` | Structural writeback and legacy helpers |

The old Quant roadmap still exists, but it is no longer the life-wide source of truth:

| Legacy surface | Path | Current role |
|---|---|---|
| Quant roadmap | `quant/roadmap.md` | Historical reference |
| Quant state | `quant/state.md` | Legacy/manual Quant state |
| Quant schedules | `quant/schedules/` | Legacy generated schedule archive |
| XP artifacts | `quant/arsenal/` | Historical and reusable Quant learning assets |

---

## 2. Daily Operating Loop

The normal v4.3 loop is intentionally small:

1. Read `life-board.md`.
2. Read today's diary if it exists.
3. Check `journal/memory.md` for hot hypotheses.
4. If there are new files in `inbox/`, route them by `inbox/00-readme.md`.
5. If Henry asks for a plan, create a conversational projection from the board.

Default planning is **not** `update-schedule`. It is:

> active track -> next artifact -> today's one useful movement

Scripts are used only when they protect a structure that is easy to damage by hand.

### Diary Mode Completion Contract

When Diary Mode analysis completes for a day, the following three steps are the **default closing actions** (unless Henry says "只调查 / 不要写回 / dry run"):

1. **Analysis Writeback** — write the analysis to `What Life Copilot Said` via `writeback-journal`.
2. **Daily Suggestion Writeback** — write a short, actionable next-day suggestion to tomorrow's `## 🧭 Daily Suggestion` via `writeback-daily-suggestion`.
3. **Inbox Audit** — list pending files in `inbox/`, suggest destinations per `inbox/00-readme.md`, but do not move or delete unless Henry explicitly asks.

The two writebacks and inbox audit are default closing steps — Henry does not need to request them each time. Details: see `AGENTS.md` §Diary Mode Completion Contract and `prompts/diary-mode.md` §Completion Contract.

---

## 3. Routing

Mode triggers are soft suggestions, not hard gates.

| Mode | When to use | Prompt |
|---|---|---|
| Diary | A specific day, reflection, memory, emotional pattern | `prompts/diary-mode.md` |
| Chat | General discussion, lightweight tasks, thought development | `prompts/chat-mode.md` |
| Study | Non-Quant learning, reading, concepts, practice | `prompts/study-mode.md` |
| Quant | Quant learning, XP artifacts, legacy Quant workflows | `prompts/quant-mode.md` |

Before routing, the assistant should usually inspect:

- `life-board.md`
- `journal/memory.md`
- today's diary, if relevant

If a keyword and the actual context disagree, route by context.

---

## 4. Writeback Boundaries

The most important safety rule is that different kinds of text go to different places.

| Content | Destination | Command / method |
|---|---|---|
| Henry's own diary continuation | `Thoughts & Reflections` | `writeback-thought` |
| Copilot analysis of a diary | `What Life Copilot Said` | `writeback-journal` |
| Next-day execution suggestion | `Daily Suggestion` (next day's diary) | `writeback-daily-suggestion` |
| Codex / Life Claude Renderer daily traces | `journal/ai-conversations/` + diary wikilink index | `writeback-ai-day` |
| Telegram / Kai raw conversation | Diary `From Kai` section | Manual paste |
| Durable memory | `journal/memory.md` | `writeback-memory` |
| Searchable insight index | `journal/insights.jsonl` | `append-insight` |

Do not use `writeback-thought` for Copilot analysis. Do not use `writeback-journal` to imitate Henry's diary voice. Analysis and next-day suggestions must go through separate input files.

Common commands:

```bash
python3 scripts/copilot.py preview-ai-day --date YYYY-MM-DD
python3 scripts/copilot.py writeback-ai-day --date YYYY-MM-DD
python3 scripts/copilot.py writeback-journal --date YYYY-MM-DD --input-file /tmp/analysis.md
python3 scripts/copilot.py writeback-thought --date YYYY-MM-DD --title "标题" --input-file /tmp/thought.md
python3 scripts/copilot.py writeback-daily-suggestion --source-date YYYY-MM-DD --input-file /tmp/suggestion.md
python3 scripts/copilot.py writeback-memory --date YYYY-MM-DD --kind "pattern" --content "..."
python3 scripts/copilot.py append-insight --date YYYY-MM-DD --kind "pattern" --content "..."
```

`append-insight` only writes `journal/insights.jsonl`. If the same idea should also become durable memory, run `writeback-memory` separately.

Low-level Codex transcript commands exist for manual recovery or precise control:

```bash
python3 scripts/copilot.py writeback-codex-thread --date YYYY-MM-DD --thread-id THREAD_ID
python3 scripts/copilot.py writeback-codex-day --date YYYY-MM-DD
python3 scripts/copilot.py export-codex-thread --thread-id THREAD_ID --output-file /tmp/thread.md
python3 scripts/copilot.py export-codex-day --date YYYY-MM-DD --output-file /tmp/day.md
```

For normal diary analysis, prefer `writeback-ai-day`.

---

## 5. Active Board And Seeds

`life-board.md` is the single source of truth for active work. Each track has:

- Active question
- Next artifact
- Stop condition
- Status

`seeds/` is the greenhouse for ideas that are valuable but not active.

A seed can become an active board track only when it has:

- a realistic 2-3 session window
- a concrete next artifact
- a stop condition
- fit with the current board

The board should stay clean. Parked ideas belong in `seeds/00-index.md`, not on the board.

---

## 6. Schedule Projection

v4.3 schedules are projections, not training-era generated plans.

Default path:

1. Read `life-board.md`.
2. Look at active tracks.
3. Pick the next artifact that matters today.
4. Make a lightweight plan in conversation or diary analysis.
5. If the plan includes a next-day suggestion, write it to tomorrow's `## 🧭 Daily Suggestion` via `writeback-daily-suggestion`.

Legacy Quant schedule generation still exists:

```bash
python3 scripts/copilot.py update-schedule --target-date YYYY-MM-DD
```

`update-schedule --date YYYY-MM-DD` only runs when that date's diary contains filled `## 📊 Legacy Quant Feedback`.

The default diary template does **not** include that section. If legacy Quant feedback is explicitly needed, paste the snippet from:

```text
templates/legacy-quant-feedback.md
```

---

## 7. Quant Tools

Quant Mode is now mostly a specialized study/project mode, not the default life loop.

Available Quant helpers:

```bash
python3 scripts/copilot.py quant-mission --xp XP-XX --date YYYY-MM-DD
python3 scripts/copilot.py quant-question-link --question "..." --top 8 --json
python3 scripts/copilot.py sync-quant-state --date YYYY-MM-DD --allow-missing-journal --chat-note "manual override"
python3 scripts/copilot.py sync-roadmap-stats
```

Retired helper commands:

- `quant-note`
- `quant-summary`

Session notes and summaries are maintained manually in `quant/arsenal/`.

---

## 8. File Rules

Naming:

- New folders and ordinary documents use lowercase kebab-case.
- `AGENTS.md` and `CLAUDE.md` stay uppercase.
- `00-index.md` and `00-readme.md` are allowed as directory entry files.
- Do not create new `01-*` sorting prefixes.

Privacy:

- `journal/` is private and gitignored.
- Personal Quant content such as resumes, schedules, projects, and career notes is gitignored.
- `inbox/`, `resources/`, `archives/`, and Obsidian local config are gitignored.

Before pushing:

```bash
git status --short
python3 -m py_compile scripts/copilot.py
git diff --check
```

---

## 9. What RFC Means

`RFC` means **Request for Comments**.

In this vault, [[life-copilot-v4.3-rfc]] is the design rationale and migration note for v4.3. It is not short for "refactor", although this version did involve a refactor of the operating philosophy.

Use the RFC when you want to understand why the system changed. Use this README when you want to know how to operate it.

---

## 10. Trial Week

v4.3 should now be tested in real use for one week.

Watch for:

- whether diary analysis routes by context correctly
- whether `life-board.md` helps or becomes clutter
- whether `inbox/` flush feels natural
- whether conversational schedule projection is enough
- whether any legacy Quant script tries to become the default again

If the system feels lighter and no critical workflow breaks, v4.3 is working.

---

*Last updated: [[2026-06-05]]*
