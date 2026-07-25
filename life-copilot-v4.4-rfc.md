# Life Copilot v4.4 RFC

> Status: implemented
> Date: 2026-07-25
> Supersedes: [[life-copilot-v4.3-rfc]]

## Problem

v4.3 correctly separated user writing, Copilot analysis and next-day suggestions, but ordinary Chat still wrote every lived detail to `Thoughts & Reflections` immediately. That duplicated the complete Codex trace and fragmented one conversation into many synthetic diary entries.

`writeback-ai-day` already refreshed the full daily trace and deduplicated `From Kai` links. Its timing was incomplete: it ran at Diary Mode entry, so discussion after the analysis—and especially the final bedtime exchange—could be absent until another task happened to refresh that date.

The rule set had also accumulated duplicate instructions. Model upgrades make some microscopic prompting obsolete, while a fully self-editing system would be unsafe. v4.4 therefore adds a constrained, evaluated feedback loop with an immutable I-level.

## Decision

### Three writing surfaces

| Surface | Ownership | Granularity |
|---|---|---|
| `From Kai` | raw evidence | one wikilink per date/source; full turns in trace |
| `Thoughts & Reflections` | Henry's lived content | one generated merged capture plus handwritten / explicit captures |
| `What Life Copilot Said` | Copilot analysis | mirror, historical anchors, memory audit |

Ordinary Chat does not write immediately. “记一下” still calls `writeback-thought`. Diary entry and bedtime close update one generated block through `writeback-chat-capture`; only the bounded block with the stable `capture-id` may be replaced.

### Bedtime is an explicit close

Project hooks use `UserPromptSubmit` to recognize a direct bedtime request and `Stop` to observe the final assistant message. A marker keyed by `session_id + turn_id` joins both events.

The model first completes merged capture and rule audit, then returns exactly one bedtime sentence. The Stop hook calls `finalize-ai-day`, which:

1. creates a missing diary from the standard template;
2. refreshes all Codex and Life Claude Renderer daily traces;
3. verifies the current request and final answer;
4. adds a fallback copy if rollout persistence is delayed;
5. normalizes `From Kai` to one link per source.

Failure is visible on stderr but never blocks the already generated bedtime sentence. If a Desktop build does not run project hooks, Chat Mode instructs the model to call the same finalizer before returning the prepared sentence.

### Constrained strange loop

The system has three levels:

- L0 runtime behaviors, editable only in mode prompts.
- L1 evolution policy, editable only in `prompts/evolution-policy.md`.
- L2 immutable kernel in `AGENTS.md`, not eligible for automation.

The fixed cycle is:

`evidence → classification → smallest patch → shadow evaluation → promotion → 7-day probation → retain or rollback`

Promotion requires an explicit system-design request or multi-date evidence, every hard golden case, improvement on the target case, no regressions, at least one recent real trace, a clean target, an isolated commit, append-only ledger entry and rollback snapshot. One close may promote at most one rule family. The promoted rule is not used recursively in the turn that created it.

## Interfaces

- `writeback-chat-capture --date --input-file [--title]`
- `writeback-ai-day --date [--create-journal]`
- `finalize-ai-day --hook-input-file [--date]`
- `audit-system-rules --date --model [--candidate-file]`
- `promote-system-rule --candidate-file`
- `rollback-system-rule --candidate-id --reason`

Evolution facts live in `journal/system-evolution.jsonl`; candidate material lives in `journal/system-evolution-candidates/`. Both remain private journal surfaces.

## Rule ownership

- `AGENTS.md`: L2 kernel, routes, entrypoints and universal writeback constraints.
- `prompts/chat-mode.md`: conversational behavior, capture timing and bedtime close.
- `prompts/diary-mode.md`: Diary analysis and the sole Completion Contract.
- `prompts/quant-mode.md` / `prompts/study-mode.md`: mode-local behavior.
- `prompts/evolution-policy.md`: L0/L1 trigger, evidence, evaluation, promotion and rollback rules.
- `scripts/copilot.py`: structural enforcement, never the source of prose behavior.

## Migration

The six auto-generated Chat entries on [[2026-07-25]] are merged without loss into the single stable capture block. Existing entries with independent narrative value, including the “显示器退烧” material on [[2026-07-24]], remain untouched.

The existing `.codex/agents/multimodal-v25.toml` remains unchanged. v4.4 only adds the project hook definition and bedtime hook handler.

## Acceptance

- Ordinary Chat does not write; explicit capture does.
- Diary entry and close update the same generated block and preserve handwritten text.
- Direct bedtime requests close; meta-discussion and quotations do not.
- Finalizer is idempotent across retries, missing diaries, midnight boundaries and delayed rollout persistence.
- L0/L1 may be evaluated; L2, whitelist and evaluation-floor changes are rejected.
- Dirty targets pause promotion; every promotion is isolated and rollback-capable.
- The standard `unittest` command discovers the formerly missed test modules and the v4.4 regression suite.
