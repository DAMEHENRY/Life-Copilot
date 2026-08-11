# Life Copilot v4.3 RFC

> Status: Draft
> Author: Henry + Claude Code
> Date: 2026-06-04
> Replaces: v4.2 (2026-06-01)

---

## 1. Why v4.3

v4.2 was built around a Quant roadmap executor: XP tasks, FULL POWER schedules, sync-quant-state gates, update-schedule triggers. That system worked because life had a clear training-phase container.

As of [[2026-06-03]], the roadmap is 100% complete. There are no pending XPs. But the old routing rules still default to XP mode, the schedule projection still assumes a training cadence, and the folder routes still point at a structure that no longer matches what Henry actually does. The system creates drag instead of lift.

v4.3 is not a feature addition. It is a **re-foundation**: keep what is load-bearing, retire what is not, and build the minimum structure for the next phase.

---

## 2. Philosophy

**Do as much as needed, as little as possible.**

This is not "do less." It is: the parts that must be hard (evidence, trace, memory provenance, writeback boundaries) stay hard. The parts that can grow naturally (project selection, schedule shape, folder contents) get left alone until a real constraint forces change.

The corollary: **every rule must justify its existence against the current phase, not against the phase that created it.**

---

## 3. Four-Quadrant Diagnosis

Before changing anything, classify every existing component:

| | **Necessary** | **Unnecessary** |
|---|---|---|
| **Exists** | Keep & strengthen | Retire (negative backlog) |
| **Not Exists** | Build (v4.3 scope) | Ignore |

### 3.1 Necessary / Exists — Keep

- **Evidence layer**: diary, memory.md, memory-archive.md, insights.jsonl, AI conversation traces. This is the provenance backbone. No change.
- **Capture layer**: inbox/, Telegram → diary flow, From Kai trace architecture. Still the lowest-friction input path.
- **Memory governance**: Active Hypotheses → Canonical → Archive remains the right shape. The 2026-08-10 calibration makes maintenance autonomous by default: semantic no-op/add/replace/promote/archive decisions happen backstage, actual changes are verified, and relational responses do not carry audit tails.
- **Writeback semantics**: diary writeback boundaries (user text vs Copilot analysis vs AI trace). Still correct.
- **Scripts**: `copilot.py` core commands (writeback, transactional `maintain-memory`, append-insight, compact-memory, quant-mission, quant-question-link, legacy schedule/state utilities). Retirement candidates below.
- **AI trace architecture**: Codex/Claudian trace files with wikilink index in diary. Proven and stable.

### 3.2 Necessary / Not Exists — Build

- **Active Board**: a single file showing what each life track is currently working on, what the next artifact is, and when to stop. Replaces the implicit "roadmap = life" assumption. → `life-board.md`
- **Index-guided routing**: instead of hard-coded mode triggers (Quant/Chat/Diary), the system reads the Active Board and memory to decide what matters today. Mode triggers become soft suggestions, not gates.
- **Schedule projection**: a lightweight replacement for `update-schedule` that does not require Quant Feedback or XP targets. Just: what is the next artifact per track, and what is today's one-thing.
- **Negative backlog**: a named list of things the system explicitly does NOT do anymore. Prevents feature creep and zombie rules.

### 3.3 Unnecessary / Exists — Retire (Negative Backlog)

These are candidates for the negative backlog. They were necessary during the roadmap phase but create drag now:

- `sync-quant-state` gate: the rule that Quant Feedback must be filled before state updates. Post-roadmap, there is no daily Quant Feedback to fill.
- `update-schedule` gate: same problem — requires filled Quant Feedback to generate next-day schedule.
- FULL POWER default: the assumption that every day should be maximized for XP throughput.
- XP-only folder routes: `quant/arsenal/` still exists but is no longer the primary output format.
- Mode trigger rigidity: `#quant` / `#YYYY-MM-DD` hard routing. Post-roadmap, conversations blend tracks.

> **Rule**: retired items are not deleted from the codebase. They are listed here so the system knows not to use them. If a track generates new XPs later, the commands still work — they just are not the default path.

### 3.4 Unnecessary / Not Exists — Ignore

- Embedding / vector index systems. Already rejected. No revisit.
- External database. Local-first stays.
- Auto-apply for internships. Manual-first stays.

---

## 4. Layer Architecture (v4.3)

The system has seven layers, bottom-up. Each layer only depends on layers below it.

```
┌─────────────────────────────────────┐
│  7. Schedule Projection             │  ← what is today's one-thing
├─────────────────────────────────────┤
│  6. Project Protocol                │  ← how a seed becomes a project
├─────────────────────────────────────┤
│  5. Active Board                    │  ← what each track is doing
├─────────────────────────────────────┤
│  4. Index-Guided Routing            │  ← which track matters now
├─────────────────────────────────────┤
│  3. Seeds                           │  ← candidate next projects
├─────────────────────────────────────┤
│  2. Capture                         │  ← inbox, Telegram, From Kai
├─────────────────────────────────────┤
│  1. Evidence                        │  ← diary, memory, traces
└─────────────────────────────────────┘
```

### Layer 1: Evidence

No change from v4.2. This is the foundation.

- `journal/YYYY/MM/YYYY-MM-DD.md` — daily diary
- `journal/memory.md` — hot memory (Active Hypotheses + Canonical)
- `journal/memory-archive.md` — cold archive
- `journal/insights.jsonl` — append-only insight log
- `journal/ai-conversations/` — AI trace files

Memory lifecycle behavior is autonomous but conservative. Diary closeout always audits backstage; other modes trigger maintenance only on a clear durable signal. New evidence should reinforce or correct an existing Active entry rather than create a near-duplicate. Canonical promotion requires repeated independent support; stale entries are archived, never silently deleted; unresolved source conflicts do not overwrite Canonical. `maintain-memory` is the transactional default, while legacy `writeback-memory` remains available for deliberate low-level appends.

### Layer 2: Capture

No change from v4.2. This is the input surface.

- `inbox/` — zero-friction capture buffer
- Telegram → From Kai → diary flow
- `writeback-ai-day` for trace archival

### Layer 3: Seeds (NEW)

A seed is a candidate next project that has not yet been promoted to a track. Seeds live in `seeds/`, and `seeds/00-index.md` is the source of truth for the seed inventory. `life-board.md` may point to the seed index, but should not duplicate the inventory. A seed is promoted to a track when:

1. It has an **active question** (what am I trying to find out?)
2. It has a **next artifact** (what is the first concrete output?)
3. It has a **stop condition** (when is this done?)

Seeds without all three stay in `seeds/`. They are not ignored — they are incubating.

### Layer 4: Index-Guided Routing (CHANGED)

v4.2 routing: hard mode triggers (`#quant`, `#YYYY-MM-DD`, else Chat).

v4.3 routing: soft context selection with an explicit gate for side-effectful workflows.

1. Read `life-board.md` — what tracks are active?
2. Read `journal/memory.md` — what hypotheses are hot?
3. Read today's diary (if exists) — what is already in motion?
4. Use the intersection to select relevant context, not to infer permission for persistent analysis.

The old mode prompts (`prompts/diary-mode.md`, `prompts/quant-mode.md`, `prompts/chat-mode.md`) are still read when the conversation clearly belongs to one mode. Context determines what is relevant, but it does not authorize side effects.

Three operations are intentionally separate:

1. **Chat** — respond naturally in the conversation. Mentioning today's experience, a major decision, or strong emotion remains Chat by default.
2. **Capture** — persist a user-provided experience into `Thoughts & Reflections` with explicit Life Copilot transcription provenance. Capture does not change the mode.
3. **Diary Analysis** — run the evidence-heavy analysis and Completion Contract. This requires an explicit `#YYYY-MM-DD`, a request to analyze/retrospect on a diary, or an already-established Diary Mode session receiving a correction.

This asymmetry is deliberate: choosing context can be soft, while granting writeback authority must be explicit. A Chat response may become deeper when the situation warrants it, but `What Life Copilot Said`, Life Board audit, inbox audit, and Daily Suggestion remain unavailable until the Diary Analysis gate is crossed.

### Layer 5: Active Board

`life-board.md` is a slow-variable active context map — not a daily planner or todo list. It replaces the implicit assumption that `quant/roadmap.md` = life.

Each track has exactly four fields:
- **Active question** — the current open question
- **Next artifact** — the next concrete output
- **Stop condition** — when to declare this done
- **Status** — one of: `active`, `waiting`, `paused`, `done`

Daily projection reads the board but does not update it by default. Board updates are event-driven and evidence-based: next artifact completed, active question answered/expired, seed promoted, track paused/waiting/done/deleted, or repeated diary evidence showing the board no longer matches life.

Periodic audit behavior: every 7-14 days, or when diary evidence suggests drift, Life Copilot reminds Henry and proposes minimal patches (add/change/delete/pause/done). Henry approves; Copilot performs the maintenance. No auto-apply without Henry's confirmation unless he explicitly asks.

### Layer 6: Project Protocol

When a seed is promoted to a track, it follows this protocol:

1. **Define the question** — what exactly are you trying to find out? (Ref: [[2026-06-02]] "defining a question is way more important than solving it")
2. **Define the first artifact** — notebook outline, 1-page memo, prototype, conversation. Not "learn X" — a concrete deliverable.
3. **Define the stop condition** — what evidence would tell you this is done?
4. **Execute** — work on the artifact.
5. **Retrospect** — write a summary. What was learned? Does the question change?

This replaces the XP lifecycle for non-Quant tracks. For Quant tracks that still use XPs, `quant-mission` and `quant-question-link` remain available, while session notes and summaries are maintained manually in `quant/arsenal/`.

### Layer 7: Schedule Projection

A lightweight replacement for `update-schedule`. Instead of generating a full schedule file from Quant Feedback:

1. Read the Active Board.
2. For each active track, identify the **next artifact**.
3. Ask: what is the **one thing** today that moves a track forward?
4. That is the schedule projection.

It does not require Quant Feedback, XP targets, or energy scores. It just asks: given what is active, what matters most today?

Schedule projection happens during diary analysis or on explicit request. It is a conversation, not a script command.

**Tomorrow Projection Input** is a low-friction input surface in the daily template, not a task list or script gate. Fields: **Tomorrow anchor** (a fixed event, a minimal artifact, or both; does not limit tomorrow to one thing), **Context / track** (natural language; Copilot maps it to board tracks during analysis), **Known limits** (known commitments/constraints; `unknown` is acceptable), **Do-not-expand** (active boundary: what this should not turn into).

Next-day execution suggestions are written to the target day's `## 🧭 Daily Suggestion` via `writeback-daily-suggestion`, using target-day voice (`today`, not `tomorrow`). The completion contract runs inbox audit before Daily Suggestion so the suggestion does not recommend actions already completed during the nightly audit/flush.

---

## 5. Negative Backlog

Items explicitly retired from active use. They still exist in the codebase but are not part of the default workflow.

| Item | Retired Because |
|------|----------------|
| `sync-quant-state` gate (requires filled Quant Feedback) | Post-roadmap, no daily Quant Feedback to fill |
| `update-schedule` gate (requires filled Quant Feedback) | Same |
| FULL POWER daily default | Not every day is a training day |
| XP-only schedule projection | Life has more tracks than Quant |
| Hard mode triggers (`#quant`, `#YYYY-MM-DD`) | Conversations blend tracks; contextual routing is better |
| `quant/roadmap.md` as life's single source of truth | Active Board replaces this role |

> **Un-retirement rule**: if a new Quant roadmap is created, or if Henry explicitly enters a training phase, these items can be reactivated. Retirement is phase-aware, not permanent.

---

## 6. Migration Path

v4.3 is a **soft migration**. No files are moved, no scripts are deleted, no existing data is changed.

What changes:
1. `life-board.md` is created (new file, root directory).
2. `seeds/` is created as the greenhouse for valuable but inactive ideas.
3. This RFC is created (new file, root directory).
4. Mode routing becomes contextual (behavioral change, no code change).
5. Schedule projection becomes conversational (behavioral change, no code change).

What stays:
1. All scripts in `scripts/copilot.py` still work.
2. All mode prompts in `prompts/` still exist.
3. `quant/roadmap.md` still exists as historical reference.
4. `quant/state.md` still exists as historical reference.
5. `quant/arsenal/` still holds all XP artifacts.

The old system is not broken. It is just not the default path anymore.

---

## 7. Success Criteria

v4.3 is working when:

1. Henry can look at `life-board.md` and know what each track is doing in 30 seconds.
2. Context selection is flexible, while Diary Analysis starts only from explicit user intent and never from Capture alone.
3. Schedule projection works without Quant Feedback.
4. New projects enter through Seeds, not through XP task creation.
5. The system feels lighter, not heavier.
6. Henry is not asked to approve routine durable-memory writes, and `What Life Copilot Said` contains no memory-audit or maintenance language.
7. Re-running the same closeout is idempotent: it does not create duplicate memory, and conflicts fail without partial mutation.

---

## 8. Open Questions

1. Should `prompts/quant-mode.md` be updated to reference the Active Board, or kept as-is for legacy Quant work?
2. Should `life-board.md` be gitignored (like diary) or committed (like prompts)?
3. How often should the Active Board be reviewed — daily during diary, or weekly?

---

*Last updated: [[2026-06-04]]*
