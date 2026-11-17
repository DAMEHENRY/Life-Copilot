# zshs internship agent records

> Status: implemented 2026-11-17.
> Date: 2026-11-17.
> Scope: Henry asked for the Codex and other agent records on the internship Windows host (zshs) to join the daily `From Kai` archive, and for the whole internship period to be pulled into one corpus for later analysis.

## Why

The internship machine holds the longest record of how Henry's research thinking changed: the prompts, the dead ends, the redefinition of the optimization target. That record was outside the vault because those agents ran on the office Windows host, not on the Mac. The daily diary could see the Mac's Codex, Claude Code, Kai and web chats, but not the conversations where the work actually happened.

The source is optional by design. The host is a work machine: it can be off, off the network, or holding a session that has nothing to do with the day. A missing machine must cost one line, not the diary analysis.

## Flow

`writeback-ai-day` gains `zshs-codex` and `zshs-claude-code` as trace sources. When the host answers over SSH, the command:

1. lists the day's Codex rollout files (`~/.codex/sessions/YYYY/MM/DD`, plus the neighbouring days for sessions that cross midnight) and the Claude Code session files touched in the day's window;
2. reads them on the host with the Anaconda Python already there, filtering each session down to its metadata and visible user/assistant records (decompressing Codex `.jsonl.zst` rollouts, dropping tool results, sidechains and synthetic messages), and returns one gzipped tar per source over stdin/stdout;
3. writes the filtered JSONL into a local cache under `~/Library/Application Support/life-copilot/zshs/`;
4. renders the same visible user/assistant messages as the Mac sources, with the headings `### zshs Codex Thread <id>` and `### zshs Claude Code Session <id>`;
5. writes the usual per-day trace files and one `From Kai` wikilink each.

The filtering is not an optimisation of the archive; it is the only workable transport. The raw tree is about 390 MiB of Codex rollouts and 96 MiB of Claude Code data, and the office-to-Mac Tailscale path measured around 20 KiB/s: a raw copy is six hours. The visible records for a 49 MiB Codex day were 74 messages and 59 KiB gzipped, so the filtered daily pull stays in seconds and the four-month backfill in minutes. The full raw remains on the host and is named in the manifest.

It never writes to the host, never reads credentials, and never deletes a remote file. The SSH host key is pinned to the Tailscale address `100.86.105.53`, so a LAN name or a new DNS answer does not silently change the peer.

When the host is unreachable, the run prints one line, marks a ten-minute cooldown (so the one-minute sync job does not pay a connect timeout every push), and leaves any existing zshs trace untouched. It is not part of the `--allow-missing-*` required-source decisions: OpenClaw/Kai and ChatGPT web stay required, zshs does not.

`refresh-ai-day` performs the same optional pull for the current day, so Kai's mirror and the other entrances see the internship conversations the same day. `--no-zshs` skips the host on either command.

## Backfill

`backfill-zshs --since 2026-07-27 --until YYYY-MM-DD` imports the internship period into one place:

- `journal/ai-conversations/zshs-internship-<start>-to-<end>/visible/codex-filtered.tar.gz` and `visible/claude-code-filtered.tar.gz` hold the filtered original JSONL, with the source's directory layout;
- `manifest.json` records host, range, file sizes, SHA-256, the extraction counts, and the remote paths where the full raw still lives;
- `index.md` is a per-day table with session/message counts and links to the per-day traces;
- the per-day `zshs-codex` / `zshs-claude-code` traces are written to the normal archive.

The diary is not touched. Historical diaries and existing traces are not rewritten; the import adds source evidence and an index beside them. This follows the same boundary as the Gemini Takeout import.

## Semantics

- Session headings carry the `zshs` prefix so the day timeline and the trace guard can tell these sessions from the Mac's.
- Message text goes through the existing Codex and Claude Code cleaners: no thinking, tool calls, subagent sidechains or injected context.
- The corpus is evidence, not the analysis. A later analysis still has to fix the comparison dimensions Kai named on 2026-11-17 (what was being optimized, what hypothesis was proposed, how it was tested, where the result differed, what changed next).
- 妙手 (CatPaw) is imported from `%APPDATA%\catpaw-moon\catpaw-memory-909489.db` (`ui_sdk_messages`, joined to `sessions` for titles), under the source name `zshs-catpaw` and the heading `### zshs CatPaw Session <id>`. Its expert/sandbox injection blocks are stripped before a message is kept.
- WorkBuddy is not imported yet: the host has only one local session, and its event stream format has not been verified. The inventory comes first, then an adapter with tests; guessing a parser would put unverified text into `From Kai`.

## Verification and rollback

Tests in `tests/test_zshs_import.py` cover the Codex, Claude Code and CatPaw renderers, the archive path guard, the cooldown, the filtered range decoder, the daily trace + `From Kai` link, the backfill corpus/manifest/index, and the timeline labels. The backfill writes only new files; removing the corpus directory and the three trace families restores the previous state, and `--force` is never used by this path.

The 2026-11-17 backfill covered 2026-07-27 to 2026-11-17: 106 Codex files / 6,411 records, 101 Claude Code files / 10,684 records and 20 CatPaw files / 862 records, i.e. 227 visible files (39.7 MiB) and 63 daily traces across 48 days with records. The raw sources on zshs were 386.7 MiB (Codex), 95.9 MiB (Claude Code) and 35.6 MiB (CatPaw, the 20 used conversations); the link measured around 20 KiB/s, which is why the visible-record transport is part of the design rather than a later optimisation.

Operational check:

    python3 scripts/copilot.py backfill-zshs --since 2026-07-27 --until 2026-11-17 --dry-run
    python3 scripts/copilot.py refresh-ai-day --date 2026-11-17
