# Source Registry and Trace-Format Consolidation

> Status: proposed (handoff; no code changed yet).
> Date: 2026-11-17.
> Scope: the source-registration debt exposed by adding zshs Codex / Claude Code / CatPaw to From Kai (commit 1d481ea). No behavior change is intended.

## Why

Adding one source to From Kai currently means editing the same fact in ten places. The zshs change needed edits in `ai_trace_path_for_date`, `TRACE_ASSISTANTS`, `TRACE_SESSION_HEADING_RE`, `TIMELINE_SESSION_HEADING_RE` / `TIMELINE_ASSISTANTS`, `writeback_ai_day` (initialisation, pull, path, link, trace list, journal bullet, no-conversations check, return dict), `zshs_sync_day`, `backfill_zshs` (sources, files, table columns, trace labels, manifest, index, return), `zshs_extract_range`, the remote reader string, and the docs and tests. Missing one place usually does not fail: the source silently disappears from preview, the timeline, the return dict, or the guard's synthetic filter.

This is not only a future-source cost. Three concrete drifts already exist:

- `preview-ai-day` does not know about zshs at all, although `writeback-ai-day` does.
- `cmd_refresh_ai_day` infers status by searching captured stdout for `"OpenClaw unavailable"` and `"zshs unavailable"`, so a wording change silently changes the status.
- `trace_message_is_synthetic` has no branch for `zshs-codex` or `zshs-catpaw`; the trace guard therefore falls back to "keep everything" for those sources.

The goal is to make a source one object, read by writeback, preview, refresh, backfill, the timeline and the guard, while keeping the on-disk format and every current behavior identical.

## Goals

1. One `SourceSpec` per source, holding its identity, labels, pull function and required/optional policy.
2. One `SourceResult` per source per day, holding status, transcript, records and detail. No status inference from log text.
3. `writeback_ai_day`, `cmd_preview_ai_day`, `backfill_zshs` and `cmd_refresh_ai_day` read the same registry and the same results.
4. One trace parser shared by the trace guard and the day timeline.
5. No output change: trace names, frontmatter, headings, message lines, From Kai bullets and order, timeline labels, read plan, and required/optional semantics stay as they are.

## Non-goals

- No new sources. WorkBuddy remains out of scope.
- No change to the zshs transport, filter or cache, and no change to web-chat syncing, WeChat importing, diary analysis, memory, the Board or the inbox.
- No historical diary or trace rewrite. The zshs corpus stays as it is.
- No monolith split in stages 1-3. Stage 4 is optional.
- No data migration and no `--force`.

## Current shape

### One source, ten edits

| Place | What it repeats |
|---|---|
| `ai_trace_path_for_date` | source whitelist and the error text |
| `TRACE_ASSISTANTS` | source -> assistant speaker for the guard |
| `TRACE_SESSION_HEADING_RE` | heading shape for the guard |
| `TIMELINE_SESSION_HEADING_RE` / `TIMELINE_ASSISTANTS` | heading shape and labels for the timeline |
| `writeback_ai_day` | init, pull, path, link, trace tuple, journal bullet, no-conversations check, return key |
| `zshs_sync_day` | the zshs-specific pull fan-out |
| `backfill_zshs` | source list, archive names, table columns, trace label map, manifest, index, return |
| `zshs_extract_range` / `ZSHS_FILTER_READER` | remote branch for a zshs source |
| Docs | file map, writeback section, README, RFC |
| Tests | patch points for the new exporter |

### Drift already present

- Preview lacks zshs. This is the cleanest proof that the registry is not shared.
- Refresh's status comes from log substrings, not from `writeback_ai_day`'s result.
- The no-conversations check is a hand-maintained conjunction of transcript variables. A new source with data but no line in that conjunction makes the command raise "No AI conversations".
- The return dict is hand-maintained (20+ keys); callers and tests read it by key.
- `trace_message_is_synthetic` is a type switch over source names and stops at the sources it knows.

### Two parsers of one trace format

`split_trace_units` (guard) and `day_timeline_messages` (timeline) each parse the same headings and message lines with their own regex. The writer emits a third convention. A heading that one parser accepts and the other does not fails silently: the trace looks right, the timeline loses the session, or the guard cannot match a message.

### One writeback function with many modes

`writeback_ai_day` currently has flags for `create_journal`, `hook_payload`, `allow_missing_openclaw`, `web_chats`, `allow_missing_web_chats`, `force`, `web_chats_synced`, `update_journal`, `pull_openclaw`, `pull_zshs`, `zshs_respect_cooldown` and `skip_unchanged`. The combinations are implicit modes. The function also owns the Codex hook fallback, WeChat import, trace writing, timeline rebuild and journal links.

### Remote readers are strings

`OPENCLAW_STORE_READER` and `ZSHS_FILTER_READER` are large raw strings with their own schema logic. Syntax errors and schema mistakes can only surface on the host; lint and unit tests cannot see them. `copilot.py` is over ten thousand lines; the zshs commit alone changed 1,234 lines in it, which is a large merge-conflict surface when another agent edits diary, WeChat or web-chat code.

## Design

### SourceSpec

A frozen dataclass. The registry order is the From Kai bullet order.

```python
@dataclass(frozen=True)
class SourceSpec:
    name: str                      # trace suffix and source id, e.g. "zshs-catpaw"
    assistant: str                 # speaker in the trace, e.g. "CatPaw"
    heading: str                   # "zshs CatPaw Session"
    trace_title: str               # "zshs CatPaw Trace"
    from_kai_description: str      # the bullet text
    pull: Callable[[date], SourceResult]
    required: bool = False         # missing without the flag is fatal
    missing_flag: str = ""         # "--allow-missing-openclaw"
    frontmatter: tuple[str, ...] = ()  # e.g. ("host: zshs",)
    synthetic: Callable[[dict], bool] | None = None  # guard helper
```

Notes:

- `heading` is the single source of truth for the guard and timeline. Legacy heading variants (`Kai / Telegram Session`, `Kai / WeChat Session`, web `Conversation`) stay as explicit patterns next to the registry until stage 3.
- `pull` returns a `SourceResult` and raises a typed `SourceUnavailable` only when the caller should decide required/optional. The orchestrator maps that to `unavailable` or re-raises.
- The zshs sources share one optional policy and cooldown; the spec should carry a `group` or a shared policy object rather than three copies.
- Web chat providers contribute specs too, but their pre-sync remains a separate step before the loop.

### SourceResult

```python
@dataclass
class SourceResult:
    status: str                    # pulled | empty | skipped | unavailable
    transcript: str = ""
    records: list[SourceRecord] = field(default_factory=list)
    detail: str = ""
    trace_path: Path | None = None
```

`writeback_ai_day` returns a derived dict: `{spec.name: result}` plus the existing top-level keys the CLI and tests use. `refresh` prints statuses from results; it must not inspect the captured log.

### Registry and orchestration

- `SOURCES: tuple[SourceSpec, ...]` for the active sources: codex, life-claude-renderer, claude-code, antigravity, openclaw, zshs-codex, zshs-claude-code, zshs-catpaw, then the web providers.
- `writeback_ai_day` iterates the list, collects results, writes the traces, rebuilds the timeline, adds one journal bullet per non-empty result, and derives the no-conversations check from `any(result.transcript) or wechat_messages`.
- The Codex hook fallback stays a Codex-only hook before the generic loop; it must not leak into other sources.
- WeChat stays outside the registry: it has its own importer, section and timeline rules. The no-conversations check includes it explicitly.
- `claudian` stays in the trace-path whitelist for old files but is not a daily source.

### Preview

Preview uses the same registry but keeps its current per-source behavior: local sources read local files, OpenClaw still pulls live as today, and zshs reads the last cached trace only (reporting its mtime and size as "cached"; "not cached" if none). Give the spec a `preview` hook (or a `preview_pull` flag) instead of forcing every source through the network; do not silently make OpenClaw offline. This removes the separate source list and fixes the current zshs drift.

### Refresh

`refresh-ai-day` keeps its output contract: a `refreshed ...` line when something changed, a `zshs: ...` line, and `openclaw: ...` as the last line (the sync job reads it). The statuses come from `SourceResult`, not log text. The `--no-openclaw` / `--no-zshs` flags mark those results `skipped`.

### One trace parser

Add `parse_trace(text) -> list[TraceSession]`, where a session holds its heading label, id, title and message units. The writer keeps emitting the same bytes. `split_trace_units` and `day_timeline_messages` both consume `parse_trace`; delete the duplicate heading regexes after the timeline tests pass. The parser must accept the existing on-disk traces unchanged, including the manual OpenClaw blocks and the web `Source:` lines.

## Migration stages

Each stage is one commit and must keep the 380-test suite green.

### Stage 0: baseline

- Run `python3 -m pytest -q tests`; expect 380 passed, 28 subtests.
- Pick fixed days: 2026-11-17 (all sources), 2026-08-06 (Codex + Claude Code on zshs), 2026-07-27 (sparse first day), 2026-11-10 (heavy Codex). Copy their trace and timeline files to a frozen fixture directory before touching code; today's files keep growing as Henry talks.
- Record one live `refresh-ai-day --date 2026-11-17` output.

### Stage 1: SourceSpec registry, no output change

- Add the dataclasses and the registry. Move each exporter behind a `pull_*` function that returns a `SourceResult`.
- Switch `writeback_ai_day` to the registry loop, then preview, then `backfill_zshs`'s label/column map.
- Keep `ai_trace_path_for_date`, the heading regexes and the guard behavior as they are; they will consume the registry in stages 2-3.
- Verify the golden trace bodies and the From Kai section are byte-identical. Preview gains the missing zshs section; that is the intended drift fix, and its own golden covers it. Update tests only at patch points; do not weaken assertions.
- Commit.

### Stage 2: structured results and status

- Remove the no-conversations conjunction and the hand-built return dict; derive both from results.
- Remove the log-substring status in `cmd_refresh_ai_day`; use results. Keep the printed lines and the last-line contract.
- Add a test matrix for required/optional: OpenClaw required, ChatGPT web required, Claude/DeepSeek/Gemini web optional, zshs optional with cooldown, WeChat best-effort.
- Commit.

### Stage 3: one trace parser

- Implement `parse_trace`; make the guard and timeline use it. Delete the duplicate heading regexes and the `trace_labels` map in `backfill_zshs`.
- Golden-check trace and timeline bytes. The timeline must still show the same labels, sessions and counts.
- Commit.

### Stage 4 (optional): split the module and the remote readers

- Move the registry and per-source pull functions into `scripts/sources/` (one module per family), leaving `copilot.py` as the CLI and orchestration layer.
- Move `OPENCLAW_STORE_READER` and `ZSHS_FILTER_READER` into real `.py` files shipped with the repo, so they can be parsed, linted and tested; the host still receives the text over stdin.
- Only start this after stages 1-3 are green. It is a maintainability change, not a correctness fix.

## Invariants

- Trace file names, frontmatter, headings and message lines are byte-identical for a fixed fixture and for the golden days (excluding the `generated_by` line if the command changes).
- One From Kai bullet per source per day, no duplicates, same order as today.
- Required/optional semantics unchanged; `--allow-missing-*` and `--no-*` behave exactly as now.
- The read plan lists the timeline first, then every trace, and includes the zshs traces.
- `refresh-ai-day` still ends with the `openclaw:` line.
- No historical diary or trace rewrite; no `--force`; the zshs corpus is untouched.

## Test plan

- Golden fixture: a temp vault with one deterministic session per source; assert the full trace bytes, the From Kai section and the timeline.
- Registry completeness: iterate `SOURCES` and assert each appears in preview, writeback, backfill (if zshs), timeline and the guard.
- Status: unavailable/empty/pulled/skipped mapping without any log text.
- Parser: the same fixture through the guard and the timeline yields the same sessions/messages.
- Required/optional matrix.
- Existing 380 tests; update patch points to the new pull functions.
- Live smoke after each stage: `refresh-ai-day --date 2026-11-17` and compare the golden bodies. A backfill rerun is optional and should use the existing 2026-07-27 to 2026-11-17 range, not create a new corpus.

## Risks and rollback

- Highest risk: transcript assembly or order changes. Mitigate with byte-level goldens, not just "contains" assertions.
- Tests patch many module globals; stage 1 will need mechanical updates. Do not delete assertions to make the refactor pass.
- `refresh`'s last-line contract is consumed by `~/.local/bin/sync-life-to-openclaw`; keep it and test it.
- `preview` for zshs must not open an SSH connection; it reads the cache only.
- Rollback is per stage: each commit is independent and there is no data migration. The zshs corpus and historical traces are not touched.

## Ready-to-paste prompt for the new session

```text
读 AGENTS.md、docs/rfcs/source-registry-rfc.md 和 docs/rfcs/zshs-internship-agent-archive-rfc.md，从阶段 0 开始。

先跑 python3 -m pytest -q tests（预期 380 passed, 28 subtests）。把 2026-11-17、2026-08-06、2026-07-27、2026-11-10 的 trace 和 timeline 复制到 frozen fixture 再记哈希（今天还在增长，不要把 live 文件直接当基线），并记一次 refresh-ai-day --date 2026-11-17 的输出。

阶段 1 只引入 SourceSpec 注册表和 pull_* 结果；trace / From Kai 字节不变，preview 补上 zshs 是预期修复。阶段 2 去掉日志嗅探和手工 no-conversations/返回 dict；阶段 3 让 guard 与 timeline 共用一个 parse_trace。每阶段一个 commit，380 tests 全过、golden 对比通过再进下一阶段。

不要改历史日记，不要用 --force，不要动 zshs 的过滤/传输，不要新增来源。WorkBuddy 仍然不做。
```
