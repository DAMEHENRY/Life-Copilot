# iA Writer + Obsidian Markdown Compatibility

## Purpose

Keep newly generated Life-vault Markdown readable and navigable in both iA Writer on iPhone and Obsidian, while preserving the vault's local-first file system and graph.

This is a forward-looking authoring profile. Do not mass-convert historical diaries, source-faithful AI traces, imported documents, archives, or technical files that require a specific renderer.

## Shared Default

Prefer these forms:

| Need | Preferred syntax |
| --- | --- |
| Headings | `#` through `######` |
| Paragraphs | Separate paragraphs with a blank line |
| Emphasis | `*italic*`, `**bold**`, `~~strike~~`, `==highlight==` |
| Lists | `- item` or `1. item` |
| Tasks | `- [ ]` and `- [x]` |
| Quote or aside | `> quoted text` |
| Inline and fenced code | Backticks and triple-backtick fences |
| Tables | Pipe tables with one physical line per row |
| Footnotes | `Text[^1]` plus a separate `[^1]: Note` definition |
| Math | `$...$` and `$$...$$` |
| Tags | `#diary` or another no-space hashtag |
| Metadata | Simple YAML frontmatter between `---` lines |
| External links | `[label](https://example.com)` |
| Internal notes | `[[note]]` or `[[note|label]]` |
| Local images | `![alt](relative/path%20with%20spaces.png)` |
| Other local files | `[label](relative/path%20with%20spaces.ext)` |

For nested lists, use four spaces. Use a blank line between structurally different blocks when it improves parser consistency.

## Wikilink Rules

iA Writer on iPhone and Obsidian both support basic wikilinks and display aliases:

```markdown
[[2026-07-29]]
[[life-board|Life Board]]
```

Default to whole-note links. Do not create a section or block link when the surrounding sentence can name the relevant section or summarize the point.

Avoid these by default:

```markdown
[[note#heading]]
[[note#^block-id]]
```

When filenames collide, use an explicit folder path that both libraries can resolve:

```markdown
[[resources/sops/00-index|SOP index]]
```

Do not use iA Writer's Location-qualified form such as `[[Location: note]]`; it is not an Obsidian vault path.

## Replace Single-App Syntax

| Avoid in new reader-facing files | Use instead |
| --- | --- |
| `> [!info] Title` | `## Title`, `**Title:**`, or a plain blockquote |
| `![[image.png]]` | `![alt](relative/image.png)` |
| `![[note]]` | A whole-note wikilink plus a short summary |
| `^block-id` / `#^block-id` | A heading or a whole-note link |
| `%% hidden comment %%` | Remove it or put machine guidance in an instruction file |
| Dataview or plugin query blocks | A static reader-facing summary or table |
| iA Content Block `/file.ext` | A link, standard image, or copied source-faithful content |
| iA `{{TOC}}` | Normal headings; let each app build navigation |
| iA `+++` page break | A heading or horizontal rule if a division is meaningful |
| Raw HTML | Standard Markdown |

iA Writer and Obsidian use different inline-footnote extensions. Use reference-style footnotes rather than iA's `[^inline note]` or Obsidian's `^[inline note]`.

## Functional Exceptions

Use non-intersection syntax only when it carries essential behavior, for example an existing Obsidian block reference, a source-faithful imported document, or a renderer-specific technical note. In a file intended for ordinary iPhone reading, add a nearby plain-text fallback so the meaning survives even when the enhancement does not render.

Do not rewrite old files merely to satisfy this profile. Normalize syntax when a file is already being substantively edited and the change does not alter provenance.

## iPhone Library Setup

In iA Writer on iPhone:

1. Open the Library organizer.
2. Choose `Edit` under Locations, then `Add Location…`.
3. Select the Life folder in iCloud Drive and open it as a folder location.
4. Keep wikilink path output set to Relative or Shortest. Prefer Relative if ambiguous filenames cause wrong destinations.

Adding the whole Life folder as a Location gives iA Writer permission to render relative local images and lets its local index power search, tags, and wikilinks.

## Sources

- [iA Writer Markdown Guide](https://ia.net/writer/support/basics/markdown-guide)
- [iA Writer Wikilinks](https://ia.net/writer/support/library/wikilinks)
- [iA Writer Cloud Storage on iPhone](https://ia.net/writer/support/library/cloud-storage/cloud-storage-iphone)
- [Obsidian Flavored Markdown](https://obsidian.md/help/obsidian-flavored-markdown)
- [Obsidian Basic Formatting Syntax](https://obsidian.md/help/syntax)
- [Obsidian Internal Links](https://obsidian.md/help/links)
