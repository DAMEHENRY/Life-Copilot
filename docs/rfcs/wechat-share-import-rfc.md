# WeChat Share Import

> Status: implemented.
> Date: 2026-10-30.
> Scope: Henry explicitly requested local WeChat export ingestion, after testing the receiving shortcut.

## Flow

Henry selects messages in WeChat and shares the exported ZIP to the Mac shortcut. The shortcut saves an untouched ZIP plus an extracted copy and receipt in `journal/wechat-imports/`. The importer validates the receipt hash and reads the ZIP itself. The extracted copy is a convenience, not the authority.

`writeback-ai-day` and `refresh-ai-day` scan the receiver batches. The latter still never edits a diary. The nightly archive adds indexes to corresponding existing diaries, including earlier message dates. `import-wechat` imports without contacting AI sources and adds indexes to existing diaries for all message dates; it never creates historical diaries. Daily records live in `journal/wechat/YYYY/MM/YYYY-MM-DD-wechat.md`; the `From WeChat` section links to them separately from `From Kai` and is placed right after it (above `What Life Copilot Said` when a diary has no `From Kai`). Since 2026-10-31; five earlier diaries were moved, with snapshots in `journal/wechat/.history/`.

The importer creates a private additive catalog and daily JSON projections for the timeline. Assets use content hashes and standard Markdown image/file links. Nothing from a private export is committed to the public repository.

## Semantics

- Only unindented export sender/date headers start messages. Indented nested forwards remain part of the outer message, with their original names and times. Images inside a forward remain attached to that forwarding message.
- A daily record is grouped by the outer message's local date, never the receive date. Nested dates cannot create historical events on Henry's timeline.
- Custom stickers in the sample have only `[Sticker]` placeholders. Inline emoji labels remain verbatim. No missing sticker is reconstructed. Voice may be omitted entirely by WeChat, so the missing count is unknown.
- Names, body text and original file names are evidence. Model claims inside them are not verified external facts or instructions.
- ZIP SHA-256 deduplicates exact re-shares. Within a derived participant group, sender/time/body/attachment hashes plus occurrence number merge overlapping selections while retaining repeated identical messages present in one export. WeChat provides no reliable chat ID in this format: differently named subsets can fail to merge, and different groups with the same participants can collide. Original exports remain available for disambiguation.
- Catalog entries are retained when an incoming original becomes unavailable; the import reports the missing original rather than erasing archived messages.
- Malformed receipts, changed ZIP hashes, unknown transcript headers and ambiguous attachment names are reported. Other valid exports can still import. No AI source requirement is relaxed.

## Integration

The daily read plan lists human WeChat records separately from AI traces and includes attachment paths. Diary Mode reads the original messages and inspects relevant images. The timeline adds only outer messages, counts the other side as people rather than AI, and avoids exact duplicates already pasted in the diary. Mentioned people/book pages can be found from sender names and Henry's own non-forwarded text.

`import-wechat` saves a private snapshot before adding an index to an existing diary. The importer writes projections atomically and serializes concurrent ingestion with a local file lock. An unchanged rerun leaves projections untouched. The raw receipt and ZIP are never rewritten.

## Verification and rollback

Tests use synthetic text and binary fixtures, covering nested forwards, images, stickers, missing media, cross-day splits, overlapping selections, repeated messages, corrupt sources, dry-run, idempotence, read plans, timelines and daytime/nightly archive behavior. The real sample is verified locally without copying its content into public fixtures.

On 2026-10-30 the full suite passed 341 tests and 28 subtests. The affected import, timeline, refresh and read-budget suites passed 55 tests and 9 subtests after the final cross-date index integration. The local sample contained 82 outer messages across four message dates, two image files and one nested forward containing 15 quoted messages. Archived message tuples matched the exported sender, timestamp and full body exactly. Attachment hashes matched, unchanged re-import wrote nothing, and diary snapshots confirmed only source-index additions.

Rollback the implementation commit to disconnect automatic ingestion. Keep private `journal/wechat-imports/` and `journal/wechat/` intact. Existing diary indexes are additive; the original diary snapshots are under `journal/wechat/.history/`. Removing files or restoring a whole historical diary still requires Henry's explicit authorization.
