# templates — System Blueprints

## Purpose
Standardized note templates that reduce activation energy for creating new documents. Keeps formatting consistent across journal entries, schedules, and other recurring note types.

## Accepts
- Note templates for any vault folder (journal, quant, resources)
- Schedule templates
- Any `.md` file that serves as a reusable structural skeleton

## Rejects
- Completed notes that used a template (→ the relevant folder)
- Copilot prompt definitions (→ `prompts/`)
- One-off documents that happen to look like a template

## Subfolders
No subfolders — flat directory. Keep it lean.

## Create-New-Folder Rule
Do not create subfolders. If template count exceeds 15, review and prune unused ones before organizing.

## Active / Important Files
- `daily-log.md` — template for journal daily entries (Daily Suggestion, Tomorrow Projection Input, Writing State; no Legacy Quant Feedback)
- `legacy-quant-feedback.md` — standalone snippet for legacy Quant state/schedule scripts; paste into journal only when explicitly needed
- `sched-library-day.md` — legacy Quant schedule template (used only by `update-schedule`; not the v4.3 default projection)
