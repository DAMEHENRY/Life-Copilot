# seeds — The Greenhouse

## Purpose

**Park valuable ideas without creating false urgency.**

Seeds are ideas, research impulses, or concepts that are worth preserving but do not belong to any active project right now. They are not todos. They are not backlogs. They are possibilities waiting for the right window.

## Rules

1. **Every seed must have a source and a reason.** Why is this worth keeping?
2. **Seeds are reviewed, not worked.** Check the index during weekly flush. Remove seeds that no longer resonate.
3. **No silent graduation.** A seed does not become a project by accident (see Upgrade Protocol below).

## Index

| Seed | Source | Confidence | Added | Status |
|---|---|---|---|---|
| [[jit-finance-denoising-seed]] | inbox flush | high | 2026-06-04 | parked |

## Upgrade Protocol: Seed → Project

A seed may be promoted to an active project only when **all four** conditions are met:

1. **2–3 session window** — There is a realistic block of time to make meaningful progress.
2. **Next artifact defined** — The first concrete deliverable is specified (a notebook, a memo, a script — not "explore the idea").
3. **Stop condition** — A clear criterion for "done for now" or "this isn't working, abandon."
4. **Active-board fit** — The seed does not displace a higher-priority active project.

If any condition is missing, the seed stays parked. No exceptions.

## Flush Integration

During inbox flush, seeds arrive here via:

- **High-confidence items** from `inbox/` that are valuable but not actionable now.
- **Low-confidence items** that couldn't be resolved in 2 minutes — better to park than to lose.

Each seed entry should include:
- `confidence: high | medium | low`
- `reason`: one line on why it's worth keeping
- `source`: where the idea came from (inbox flush, conversation, reading, etc.)

## Maintenance

- Review the index during every inbox flush.
- Prune seeds that have sat untouched for 3+ months and no longer resonate.
- A pruned seed is not lost — it's in git history.
