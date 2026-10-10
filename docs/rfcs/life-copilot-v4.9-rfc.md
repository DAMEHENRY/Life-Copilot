# Life Copilot v4.9 RFC

> Status: in progress. Code, the entry file and the sync job landed on 2026-10-10 at Henry's request; the week of observation runs to 2026-10-17.
> Date: 2026-10-10
> Extends: [[life-copilot-v4.8-rfc]]

## Problem

**The Telegram entrance was a second system.** Kai answers on Telegram from an always-on host with a read-only mirror of the vault. Until this version it also had its own instruction file (mostly the agent runtime's default template), its own long-term memory file, a nightly job that promoted notes into that memory, and a snapshot of each conversation written into a notes folder. Two things followed.

- **A rule agreed in conversation did not hold.** The runtime loads the workspace instruction file in every session and does not load the memory file. On 2026-10-09 Henry asked for every reply to start from the diary, and Kai stored that in its memory file. The next morning's session never saw it. Across four days, the first message after each new session was answered within seconds with no file read.
- **The second memory aged on its own.** Its opening section, written in May as "read this every morning", still described May.

**The two sides only met at night.** `writeback-ai-day` runs when the diary analysis starts. During the day Kai could not read what was said to Claude Code or Codex, and they could not read what was said to Kai. On 2026-10-09 Henry pasted one side's reply into the other by hand.

**The machines are not symmetrical.** The laptop that holds the vault is offline whenever its lid is closed. The host that runs Kai stays on. The mirror was pushed every 15 minutes, so the last minutes before the lid closed did not arrive, and those are the diary lines and conversations most likely to be continued from the phone. The link between the two is relayed and times out: the sync log held 375 connection timeouts by 2026-10-10.

## Decision

### One system, with Kai as an entrance

Kai keeps three things: the Telegram channel, the read-only mirror, and a search index over it. Rules and memory belong to the vault, and the laptop stays the only writer.

- **Rules.** `prompts/telegram-entry.md` is Kai's instruction file. It travels with the mirror. On the host, a file watch rebuilds the workspace instruction file from it plus a local file of host-only notes (tool addresses, paths), which stay out of this repository. A pushed file that does not start with the entry file's title, or whose size is out of range, is refused and the current instructions stay.
- **Memory.** The host's own memory writers are off: the nightly promotion, the per-session snapshot, and the flush before compaction. What it had written is sealed in an archive folder outside the index. The index covers the mirrored `journal/` and Kai's own sessions; the sessions are the same-day buffer until the vault has archived them.
- **Writes.** Nothing is written from the entrance. Diary Mode, the bedtime close, memory maintenance, page updates and reminders run on the laptop, and the entry file tells Kai to say so when asked. What Henry says on Telegram reaches the diary through the trace, as before.

The entry file is not one of the four mode prompts, so the L0 evolution loop cannot edit it. It changes when Henry asks.

### A refresh between diary analyses

`refresh-ai-day` brings a day's traces and timeline up to date without being an archive run. It reuses `writeback-ai-day`'s importers and trace guard with five differences:

1. **It does not touch the diary.** The diary is not required, not created, and its From Kai index is not rewritten. Henry may be typing in that file.
2. **It never syncs web chats.** That sync opens Chrome.
3. **An unreachable Kai is normal.** The existing Kai trace is left as it is. `--no-openclaw` skips the connection altogether.
4. **A trace that would come out identical is not written.** A run with nothing new changes no file and prints nothing but its status line.
5. **It never forces.** Messages a source no longer has stay in the trace.

The nightly `writeback-ai-day` is unchanged and stays the authoritative archive: it still requires Kai and the web sync, still reports what it kept, and still takes the earlier day along.

### Push before the lid closes, pull when it opens

The sync job on the laptop now runs every minute and usually does nothing.

- **Idle check.** It looks for a mirrored file, a Claude Code or Codex session file, or the renderer history newer than the last pushed snapshot. With none, and a push less than 15 minutes old, it exits. The check takes about a tenth of a second.
- **On a change**, it runs `refresh-ai-day` for today, then pushes the mirror. So the diary lines and conversations of the last minute are on the host when the lid closes, and the mirror then stands still because nothing new is being produced on the laptop.
- **Kai's conversations are pulled** at most every 10 minutes, as part of the same refresh. After the laptop wakes, the first run pulls, so what was said on Telegram on the way is in the vault within about a minute of opening the lid.
- **Just after midnight** it also refreshes the previous day, so its last messages land.
- **A failed push** is retried once in the same run, then with a growing wait between runs (1, 2, 4, 8, then 15 minutes), and the log says when it recovers.

### What the script guarantees

1. `refresh-ai-day` leaves the diary file byte-identical, including its modification time.
2. Two runs over the same sources write once.
3. With `--no-openclaw`, or with Kai unreachable, the Kai trace is byte-identical afterwards.
4. A day with no conversation yet is not an error.
5. `writeback-ai-day` behaves as before when none of the new options is passed.

### Not changed

- L2, the diary's sections, the trace format and the timeline format.
- `writeback-ai-day`, `finalize-ai-day`, and the rule that Kai and the web chats are required evidence for the nightly archive.
- The mirror's contents and direction.

### Left out of this version

- **Web and phone-app chats during the day.** They only reach the vault through Chrome on the laptop, at night. Moving that sync to the always-on host needs a logged-in browser there.
- **An outbox** for requests made on Telegram that should be written at once. The trace carries them to the nightly capture; this waits until that proves too slow.
- **An "as of" line in the timeline.** It would make the file change on every run. The mirror's `.last-sync` gives the time, and the entry file explains that a mirror standing still while the laptop is closed is complete.
- **A direct link between the two machines.** Both ends run a proxy that captures the tunnel's traffic. A trial on 2026-10-10 was rolled back; the retry and backoff above are what this version relies on.
- **The runtime's pre-reply recall plugin.** It was switched on for Kai on 2026-10-10 and off again that evening. On real messages it mostly ran into its 15 s limit and returned nothing (one success, in 13.7 s), and every reply waited for it. The entry file has Kai search and read the sources itself, which is what found the two-month-old diary entry mentioned under Acceptance.

## Interfaces

- `python3 scripts/copilot.py refresh-ai-day [--date YYYY-MM-DD] [--no-openclaw] [--verbose]`. The last line is `openclaw: pulled`, `openclaw: skipped` or `openclaw: unavailable`; a line starting `refreshed` appears only when a file was written.
- `writeback_ai_day()` gains `update_journal`, `pull_openclaw` and `skip_unchanged`, and its result gains `openclaw_status`. `write_ai_trace()` gains `skip_unchanged`.
- `prompts/telegram-entry.md`.
- Outside this repository, on the two machines: the laptop's launchd job and sync script, and the host's file watch and rebuild script. They hold machine names and paths.

## Rule ownership

- `AGENTS.md`: the file map row for the entry file, and the sentence on when a day is archived.
- `prompts/telegram-entry.md`: what Kai reads before replying, how it replies, what it does not do, and how fresh the mirror is.
- `README.md`: the command and the sync job in the writeback section.

## Migration

1. Kai's old instruction file, memory file and notes were backed up on the host; the notes moved to an archive folder outside the index. Nothing was deleted.
2. The index was rebuilt once after its path pattern changed to skip dot-folders (superseded page versions).
3. The previous sync script and launchd job were kept next to the new ones.
4. Rollback: restore the previous sync script and the 15-minute interval; disable the host's file watch and copy back the previous instruction file. `refresh-ai-day` can stay; nothing calls it then.

## Acceptance

Measured on 2026-10-10:

- 703 tests pass: the 694 from before and 9 new ones in `tests/test_refresh_ai_day.py` for the five guarantees.
- A real `refresh-ai-day` for the day took 1.9 s including the pull from Kai. A second run wrote nothing. The diary's size and modification time were unchanged.
- The new sync script: 3.5 s for a run that refreshed and pushed, 0.07 s for an idle run.
- The entry file was on the host within a minute of being written in the vault, pushed by the launchd job. The rebuilt instruction file was byte-identical to the entry file plus the local notes. Touching the entry file in the vault started the host's rebuild 33 s later.
- Run by launchd, the job pulled a Telegram conversation that was still going on and wrote it into the day's Kai trace and timeline, ten minutes after the previous pull.
- In a test session on the delivered instructions, Kai read the day's timeline and Claude Code trace, said what that day's Claude Code work had been, and answered a `#YYYY-MM-DD` request by saying it runs on the laptop.
- In Henry's own Telegram session, after the new instructions: the first reply after a new session read the day's diary, the page and trail of the person in the screenshot, the previous day's timeline and `chat-mode.md` before answering (42 s; that morning the same kind of message was answered in 12 s with no read). A later message was answered from a diary entry two months old that Kai found by searching.

Not yet observed, and what the week is for:

- Closing the lid within a minute of a diary edit, then asking Kai about it.
- Opening the lid after a Telegram conversation, then asking Claude Code or Codex about it.
- The backoff during a real outage, and the recovery line.
- A full day of the one-minute job on battery.
