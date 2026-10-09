# Life Copilot v4.8 RFC

> Status: in progress. Steps 1 to 4 landed on 2026-10-09 at Henry's request; the week of observation runs to 2026-10-16.
> Date: 2026-10-09
> Extends: [[life-copilot-v4.5-rfc]]

## Problem

**A day's AI conversations are stored by source, and the day happened in time.** `writeback-ai-day` writes one trace per source, and inside a trace one session after another. Every message carries its time, but the order across sources and sessions exists only in those stamps, and the reader has to interleave them by hand. On 2026-10-08 the day's four traces were 198 KB in 13 reads. The Codex trace alone takes nine reads, and only after it does the reader reach a Claude Code conversation that ran in the same minutes as one of the Codex sessions.

Three things the diary analysis needs only show on a time axis:

- **What ran side by side.** On 2026-10-08, 26 of the 275 minutes with a conversation open had two or more open; on 2026-10-06, 44 of 250.
- **When nothing ran.** A stretch with no message in any source is information about the day, and no single trace shows it.
- **The shape of the day.** The first and last message, the long blocks, the scattered one-line questions.

**The data is already there.** An audit on 2026-10-09 found a timestamp on about 19,000 messages in 2,528 sessions across every source, the one-off Gemini history included. One session has none (a Codex session on 2026-06-01), and three early hand-made files do not use the message format at all. Nothing has to change in an importer.

## Decision

### A timeline per day, derived from the traces

`journal/ai-conversations/YYYY/MM/YYYY-MM-DD-timeline.md` puts every session of the day on one time axis. It is built from the day's trace files, not from the sources, so it includes what the trace guard merged back and what Henry pasted by hand, and it can be built for a day whose sources are long gone. It is rebuilt on every `writeback-ai-day`. It is not a trace: the trace glob does not match it, the diary's From Kai section does not link it, a people or book page cannot cite it, and local recall does not index it.

A **segment** is a run of messages in one session with no silence over 20 minutes. One line per segment, in order of start time:

```markdown
## Timeline

- 08:01–09:43 · Codex 01a118d0 · Henry 20, AI 20 · `start of the lecture, I will ask as we go`
- 09:03–09:04 · Codex 01a118d3 · Henry 1, AI 1 · `a side question`
- 09:43–11:30 · no messages for 1h 47m
- 11:30–11:40 · Claude Code ea8d6c7d `Lecture notes` · Henry 1, AI 1 · `tidy the notes`
- 22:21 · Claude Code ea8d6c7d `Lecture notes` · Henry 0, AI 1 · (reply only)

## Side by side

- 09:03–09:04 · Codex 01a118d0 + Codex 01a118d3
```

- **The session** is named by its source and the first eight characters of its id, then its title where the source gives one.
- **The topic** is the first line Henry typed in that segment, cut to 48 characters. It is his text, not a summary: nothing in the file is written by a model. Text a client put into his turn (a page-open marker, pasted content, the file list in front of a request) is stepped over. Titles and topics are inline code, so a wikilink inside them links nothing.
- **A quiet line** marks 60 minutes or more with no message in any session.
- **Side by side** lists the minutes in which two or more sessions had a segment open.
- **The header** says what the file is and gives the day in one line: first and last message, sessions, segments, minutes inside a segment and how many of them were shared.

The 2026-10-08 timeline is 4,340 bytes for 198 KB of traces.

### What the script guarantees

1. The timeline is a function of the day's trace files. The same traces give the same bytes, and an unchanged file is not rewritten.
2. Building it reads the traces and writes one file. It cannot change a trace or the diary, and a failure to build it prints a warning and does not fail the archive.
3. Every timestamped message under a session heading is counted in exactly one segment.
4. A session opens only at a heading whose id looks like an id, and a message counts only when a known speaker wrote it. A heading quoted inside an answer, or a line of a pasted chat, starts nothing.

### Reading

The read plan that `writeback-ai-day` and `check-read-budget --date` print names the timeline on its own line in front of the traces. It is read once, first. The traces are then read in full as before; the timeline replaces none of them.

Two limits are written into every timeline file, where each reader meets them:

- **It is an index.** Quotes and claims come from the traces.
- **A silence only means no AI conversation.** It does not say nothing happened.

### Not changed

Traces, importers, the trace guard, and the From Kai index of one link per source. Times stay to the minute, as the traces have them.

### Left out of this version

- **A picture.** The same segments could feed a drawing of parallel lanes around a time axis. It would help Henry see a day; the model reading the day gains nothing from it over the list. Decide after the list has been in use.
- **Other lanes.** Pasted chat exports carry their own times, and so do workout records. They could sit on the same axis.
- **Topics written by a model.** They would make the file something other than a function of the traces.
- **Importer drift the audit surfaced.** Recent Codex traces keep a page-open marker and a file list in Henry's turn. The timeline steps over them; removing them is the importer's job and a separate change.

## Interfaces

| Command | Change |
|---|---|
| `writeback-ai-day`, `finalize-ai-day` | after the traces are written, rebuild the day's timeline; the result names its path |
| `day-timeline --date D [--dry-run]` | new: build the timeline from the traces already on disk, without contacting any source |
| `check-read-budget --date D` and the plan `writeback-ai-day` prints | one line for the timeline, in front of the trace list |
| `tools/recall/recall.py` | skips `*-timeline.md` |

## Rule ownership

- **AGENTS.md** (requested by Henry): the timeline in the file-map row for AI traces, and in the sentence that describes the read plan.
- **prompts/diary-mode.md** (L0 candidate): step 0.5 reads the timeline before the traces. Promoted through the evolution policy.

## Migration

Each step is one commit. If work stops between two steps, Diary Mode still runs.

1. **This RFC.** Done (1efa224).
2. **Code and tests**: the timeline, `day-timeline`, the read-plan line, the recall filter. From this step every `writeback-ai-day` writes the file, and nothing yet tells a reader to open it. Done (f58c111).
3. **AGENTS.md**: manual commit. Done (73f036c).
4. **diary-mode.md**: candidate, review, `promote-system-rule`. Done: `diary-reads-the-day-timeline-first` (d74f595), on probation until 2026-10-16; the prompt grew by 116 bytes and stays under its baseline. The v4.7 rule on the same file is on probation until 2026-10-11, so a rollback of that one has to roll this one back first.
5. **Observe for a week**, then decide on the picture and the other lanes. Old days get a timeline when they are looked at, with `day-timeline`; there is no bulk backfill.

## Acceptance

- Tests pass, and prompts/diary-mode.md stays within its read-budget baseline.
- After a week of nightly runs: every analysed day has a timeline, each one fits one read, and no trace or diary was changed by building one.
- Running `writeback-ai-day` twice on the same day leaves the timeline byte-identical.
- The read receipt of a diary analysis names the timeline next to the traces.
