#!/usr/bin/env python3
"""
Life Copilot — lean orchestration utilities.

Only structural write commands that are unsafe for Claude to do freehand:
writeback-journal, writeback-thought, writeback-daily-suggestion,
writeback-memory, append-insight, compact-memory, quant-mission,
quant-question-link, sync-quant-state, sync-roadmap-stats, update-schedule.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Paths (new flat structure)
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
JOURNAL_DIR = ROOT / "journal"
MEMORY_FILE = JOURNAL_DIR / "memory.md"
MEMORY_ARCHIVE_FILE = JOURNAL_DIR / "memory-archive.md"
INSIGHTS_FILE = JOURNAL_DIR / "insights.jsonl"
ROADMAP_FILE = ROOT / "quant" / "roadmap.md"
QUANT_STATE_FILE = ROOT / "quant" / "state.md"
QUANT_ARSENAL_DIR = ROOT / "quant" / "arsenal"
SCHEDULES_DIR = ROOT / "quant" / "schedules"
TEMPLATES_DIR = ROOT / "templates"
SCHED_LIBRARY_DAY_TEMPLATE = TEMPLATES_DIR / "sched-library-day.md"
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
CODEX_SESSION_INDEX = CODEX_HOME / "session_index.jsonl"
CODEX_SESSIONS_DIR = CODEX_HOME / "sessions"

PHASE_PROTOCOLS: Dict[str, str] = {
    "Landing":        "Re-acclimate after time off or disruption. Prioritize routine rebuild and gentle momentum.",
    "Build":          "High-intensity deep work. Execute pending tasks with full focus.",
    "Study":          "Learning-focused phase. Prioritize course material and conceptual understanding.",
    "Market Waiting": "Light maintenance while external factors are pending. Review, organize, refine.",
    "Recovery":       "Low-intensity day. Protect rest, light review only if energy permits.",
    "Review":         "Retrospective and planning. Audit progress, update roadmap, consolidate learnings.",
}

AI_CONVERSATIONS_DIR = JOURNAL_DIR / "ai-conversations"
CLAUDIAN_SESSIONS_DIR = ROOT / ".claudian" / "sessions"
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects" / "-Users-henry-Library-Mobile-Documents-iCloud-md-obsidian-Documents-Life"
LIFE_CLAUDE_RENDERER_HISTORY = ROOT / ".obsidian" / "plugins" / "life-claude-renderer" / "history.json"

MEMORY_RETENTION_DAYS = 30

DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
JOURNAL_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
XP_OPEN_RE = re.compile(r"^- \[ \] \*\*(XP-[^*]+)\*\*: (.+)$")
XP_DONE_RE = re.compile(r"^- \[x\] \*\*(XP-[^*]+)\*\*: (.+)$", re.IGNORECASE)
XP_TAG_RE = re.compile(r"#(course|lab)\b", re.IGNORECASE)
MEMORY_CITATION_RE = re.compile(r"\n?<oai-mem-citation>.*?</oai-mem-citation>\s*", re.DOTALL)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def read_text(path: Path) -> str:
    """Read UTF-8 text with iCloud retry."""
    for _ in range(3):
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            time.sleep(0.05)
    raw = path.read_bytes()
    return raw.decode("utf-8", errors="replace")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def parse_date_str(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def parse_date_or_today(value: Optional[str]) -> date:
    return parse_date_str(value) if value else date.today()


def journal_path_for_date(d: date) -> Path:
    nested = JOURNAL_DIR / d.strftime("%Y") / d.strftime("%m") / f"{d.isoformat()}.md"
    if nested.exists():
        return nested
    flat = JOURNAL_DIR / f"{d.isoformat()}.md"
    if flat.exists():
        return flat
    return nested


def normalize_xp_id(raw: str) -> str:
    txt = raw.strip().replace("_", "-")
    txt = re.sub(r"\s+", "-", txt)
    txt = re.sub(r"-{2,}", "-", txt)
    if not txt:
        raise ValueError("xp is required")
    if txt.upper().startswith("XP"):
        txt = "XP" + txt[2:]
    if not txt.upper().startswith("XP-"):
        txt = "XP-" + txt[2:] if txt.upper().startswith("XP") else f"XP-{txt}"
    tail = txt[3:]
    tail = re.sub(r"[^A-Za-z0-9-]+", "-", tail).strip("-")
    if not tail:
        raise ValueError(f"invalid xp id: {raw}")
    return f"XP-{tail.upper()}"


def xp_slug(xp_id: str) -> str:
    slug = normalize_xp_id(xp_id).lower()
    slug = re.sub(r"[^a-z0-9-]+", "-", slug)
    return re.sub(r"-{2,}", "-", slug).strip("-")


def find_xp_task(xp_id: str) -> str:
    if not ROADMAP_FILE.exists():
        return ""
    needle = normalize_xp_id(xp_id)
    for line in read_text(ROADMAP_FILE).splitlines():
        m = XP_OPEN_RE.match(line.strip()) or XP_DONE_RE.match(line.strip())
        if m and normalize_xp_id(m.group(1)) == needle:
            return m.group(2).strip()
    return ""


def find_xp_tag(xp_id: str) -> str:
    """Return 'course' or 'lab' based on #tag in roadmap. Default: 'lab'."""
    if not ROADMAP_FILE.exists():
        return "lab"
    needle = normalize_xp_id(xp_id)
    for line in read_text(ROADMAP_FILE).splitlines():
        m = XP_OPEN_RE.match(line.strip()) or XP_DONE_RE.match(line.strip())
        if m and normalize_xp_id(m.group(1)) == needle:
            tag_m = XP_TAG_RE.search(line)
            return tag_m.group(1).lower() if tag_m else "lab"
    return "lab"


def quant_mission_file(xp_id: str) -> Path:
    return QUANT_ARSENAL_DIR / f"{xp_slug(xp_id)}-mission-guide.md"






def format_day_label(d: date) -> str:
    return d.strftime("%A, %b %-d, %Y") if os.name != "nt" else d.strftime("%A, %b %#d, %Y")


def format_chat_timestamp(value: str) -> str:
    """Format a Codex UTC timestamp in the local timezone for diary chat logs."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
    hour = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{dt.month}/{dt.day}/{dt.year % 100:02d} {hour}:{dt.minute:02d} {ampm}"


def timestamp_to_local_date(value: str) -> Optional[date]:
    """Convert an ISO timestamp string to its local-timezone date, or None."""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().date()
    except (ValueError, TypeError, AttributeError):
        return None


def ai_conversation_dir_for_date(d: date) -> Path:
    return AI_CONVERSATIONS_DIR / d.strftime("%Y") / d.strftime("%m")


def ai_trace_path_for_date(d: date, source: str) -> Path:
    if source not in {"codex", "claudian", "life-claude-renderer"}:
        raise ValueError(f"Unsupported source: {source}. Use 'codex', 'claudian', or 'life-claude-renderer'.")
    return ai_conversation_dir_for_date(d) / f"{d.isoformat()}-{source}-trace.md"


def obsidian_wikilink_for_path(path: Path) -> str:
    return f"[[{path.stem}]]"


def format_obsidian_link(target_stem: str, alias: str = "", heading: str = "") -> str:
    """Build an Obsidian wikilink with optional heading anchor and alias.

    Examples:
        format_obsidian_link("xp-31-derivation-guide")
        → [[xp-31-derivation-guide]]
        format_obsidian_link("xp-31-derivation-guide", heading="Shrinkage Estimators")
        → [[xp-31-derivation-guide#Shrinkage Estimators]]
        format_obsidian_link("xp-31-derivation-guide", alias="Why does shrinkage help?", heading="Shrinkage Estimators")
        → [[xp-31-derivation-guide#Shrinkage Estimators|Why does shrinkage help?]]
    """
    link = target_stem
    if heading:
        link = f"{link}#{heading}"
    if alias:
        link = f"{link}|{alias}"
    return f"[[{link}]]"


def parse_markdown_headings(text: str) -> List[Tuple[int, str]]:
    """Return list of (level, heading_text) for all headings in markdown text.

    Level 1 for '#', level 2 for '##', etc. Only heading text is returned
    (without the leading '#' markers).
    """
    headings: List[Tuple[int, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") and not stripped.startswith("```"):
            level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped[level:].strip()
            if title and level <= 4:
                headings.append((level, title))
    return headings


def iterate_quant_files() -> List[Path]:
    """Yield markdown files from quant/arsenal/**/*.md plus quant/roadmap.md."""
    files: List[Path] = []
    if QUANT_ARSENAL_DIR.exists():
        files.extend(sorted(QUANT_ARSENAL_DIR.glob("**/*.md")))
    if ROADMAP_FILE.exists() and ROADMAP_FILE not in files:
        files.append(ROADMAP_FILE)
    return files


_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "out", "off", "over",
    "under", "again", "further", "then", "once", "here", "there", "when",
    "where", "why", "how", "all", "both", "each", "few", "more", "most",
    "other", "some", "such", "no", "nor", "not", "only", "own", "same",
    "so", "than", "too", "very", "just", "and", "but", "or", "if", "while",
    "about", "up", "down", "it", "its", "that", "this", "what", "which",
    "who", "whom", "these", "those", "i", "me", "my", "we", "our", "you",
    "your", "he", "him", "his", "she", "her", "they", "them", "their",
    "use", "used", "using",
})


def _tokenize(text: str) -> List[str]:
    """Lowercase alphanumeric tokens, filtering stop words. Deduplicated."""
    tokens = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", text.lower())
    seen: set = set()
    result: List[str] = []
    for t in tokens:
        if t not in _STOP_WORDS and len(t) > 1 and t not in seen:
            seen.add(t)
            result.append(t)
    return result


_BODY_QUESTION_RE = re.compile(
    r"(?:"
    r"^#{4,6}\s+.+\?$"       # h4-h6 ending with ?
    r"|^\s*[-*]\s+.+\?$"     # bullet ending with ?
    r"|^\s*\d+[.)]\s+.+\?$"  # numbered item ending with ?
    r"|^\s*[-*]\s+\*\*.+?\*\*"  # bullet with bold text (checkpoint question)
    r"|^.+\?$"                # any line ending with ? (catch-all)
    r")",
    re.MULTILINE,
)


def _score_file(question_tokens: List[str], path: Path, content: str, xp_boost: str = "") -> dict:
    """Score a quant file against a tokenized question.

    Returns a dict with score breakdown and matched headings.
    """
    stem = path.stem.lower()
    stem_tokens = set(re.findall(r"[a-z0-9]+", stem))
    q_set = set(question_tokens)

    # Score from filename stem
    stem_hits = sum(1 for t in question_tokens if t in stem_tokens)
    stem_score = stem_hits * 3.0

    # XP boost: if the file stem or content mentions the target XP, add bonus
    xp_bonus = 0.0
    if xp_boost:
        xp_lower = xp_boost.lower()
        if xp_lower in stem or xp_lower in content[:500].lower():
            xp_bonus = 12.0

    # Score from headings — use top-3 capped, not sum of all
    headings = parse_markdown_headings(content)
    heading_scores: List[Tuple[int, str, float]] = []
    for level, title in headings:
        h_tokens = set(_tokenize(title))
        hits = sum(1 for t in question_tokens if t in h_tokens)
        if hits > 0:
            weight = (5 - level) * 1.5
            heading_scores.append((level, title, hits * weight))

    heading_scores.sort(key=lambda x: x[2], reverse=True)
    heading_score = sum(h for _, _, h in heading_scores[:3])

    # Score from body — scan full content, detect question-like lines
    lines = content.splitlines()
    body_token_hits = 0
    body_questions: List[dict] = []
    current_heading = ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            h_text = stripped.lstrip("#").strip()
            if h_text:
                current_heading = h_text
            continue
        lower = stripped.lower()
        tokens_in_line = set(re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", lower)) - _STOP_WORDS
        overlap = q_set & tokens_in_line
        if not overlap:
            continue
        body_token_hits += len(overlap)
        is_question = (
            stripped.endswith("?")
            or re.match(r"^\s*[-*]\s+\*\*", stripped) is not None
            or re.match(r"^\s*\d+[.)]\s+.*\?$", stripped) is not None
        )
        if is_question and len(overlap) >= 2:
            body_questions.append({
                "line": stripped[:120],
                "heading": current_heading,
                "overlap": len(overlap),
                "tokens": sorted(overlap),
            })

    body_score = min(body_token_hits * 0.2, 5.0)
    body_question_bonus = 0.0
    best_body_heading = ""
    if body_questions:
        body_questions.sort(key=lambda q: q["overlap"], reverse=True)
        best = body_questions[0]
        body_question_bonus = best["overlap"] * 4.0
        best_body_heading = best["heading"]

    total = stem_score + xp_bonus + heading_score + body_score + body_question_bonus

    # Pick best heading: prefer a heading-level match, fall back to body question anchor
    best_heading = ""
    if heading_scores:
        best_heading = heading_scores[0][1]
    elif best_body_heading:
        best_heading = best_body_heading

    return {
        "path": path,
        "stem": path.stem,
        "total": round(total, 2),
        "stem_score": round(stem_score, 2),
        "xp_bonus": round(xp_bonus, 2),
        "heading_score": round(heading_score, 2),
        "body_score": round(body_score, 2),
        "body_question_bonus": round(body_question_bonus, 2),
        "best_heading": best_heading,
        "heading_matches": [(lv, h, round(s, 2)) for lv, h, s in heading_scores[:5]],
        "body_questions": body_questions[:3],
    }


def cmd_quant_question_link(args: argparse.Namespace) -> None:
    """Search quant files for question-link candidates. Read-only, no mutation."""
    question = args.question.strip()
    if not question:
        raise ValueError("--question is required")

    question_tokens = _tokenize(question)
    if not question_tokens:
        raise ValueError("Question produced no meaningful tokens after filtering stop words.")

    xp_boost = ""
    if args.xp:
        xp_boost = normalize_xp_id(args.xp)

    files = iterate_quant_files()
    if not files:
        print("[warn] No quant files found in quant/arsenal/ or quant/roadmap.md")
        return

    top_n = args.top or 8

    # Score all files
    results: List[dict] = []
    for path in files:
        try:
            content = read_text(path)
        except Exception:
            continue
        result = _score_file(question_tokens, path, content, xp_boost=xp_boost)
        if result["total"] > 0:
            results.append(result)

    results.sort(key=lambda r: r["total"], reverse=True)
    top = results[:top_n]

    if args.json:
        output = {
            "question": question,
            "question_tokens": question_tokens,
            "xp_boost": xp_boost,
            "search_scope": [str(p.relative_to(ROOT)) for p in files],
            "note": "Lexical first-pass retrieval only; inspect candidates and run manual rg searches before deciding.",
            "candidates": [
                {
                    "file": str(r["path"].relative_to(ROOT)),
                    "stem": r["stem"],
                    "score": r["total"],
                    "score_breakdown": {
                        "stem": r["stem_score"],
                        "xp_bonus": r["xp_bonus"],
                        "heading": r["heading_score"],
                        "body": r["body_score"],
                        "body_question_bonus": r["body_question_bonus"],
                    },
                    "best_heading": r["best_heading"],
                    "heading_matches": [
                        {"level": lv, "heading": h, "score": s}
                        for lv, h, s in r["heading_matches"]
                    ],
                    "body_questions": r.get("body_questions", []),
                }
                for r in top
            ],
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return

    # Human-readable output
    print(f"=== Quant Question-Link Retrieval ===")
    print()
    print(f"Question: {question}")
    print(f"Tokens:   {', '.join(question_tokens)}")
    if xp_boost:
        print(f"XP boost: {xp_boost}")
    print(f"Scope:    {len(files)} files searched")
    print()

    if not top:
        print("No matching files found. Consider creating a new note in quant/arsenal/.")
        return

    print(f"--- Top {len(top)} Candidates ---")
    print()
    for i, r in enumerate(top, 1):
        rel = r["path"].relative_to(ROOT)
        print(f"  {i}. {rel}")
        print(f"     Score: {r['total']}  (stem={r['stem_score']} xp={r['xp_bonus']} heading={r['heading_score']} body={r['body_score']} q_bonus={r['body_question_bonus']})")
        if r["best_heading"]:
            print(f"     Best heading: \"{r['best_heading']}\"")
        if r["heading_matches"]:
            matches_str = ", ".join(f"\"{h}\" ({s})" for _, h, s in r["heading_matches"][:3])
            print(f"     Top headings: {matches_str}")
        if r.get("body_questions"):
            for bq in r["body_questions"][:2]:
                print(f"     Body Q (overlap={bq['overlap']}, under \"{bq['heading']}\"): {bq['line'][:90]}")
        print()

    print("--- Suggested Obsidian Links ---")
    print()
    alias = question
    for r in top[:3]:
        stem = r["stem"]
        heading = r["best_heading"]
        link = format_obsidian_link(stem, alias=alias, heading=heading)
        print(f"  - {link}")
    print()

    print("  ⚠ Ranking is lexical. Open candidates and run additional rg searches")
    print("    with synonym/mechanism keywords before creating new notes.")
    print()

    print("--- Decision Checklist ---")
    print()
    print("  □ 1. Full answer? → Use alias wikilink with heading anchor.")
    print("  □ 2. Broad answer? → Link + add a short jump hint.")
    print("  □ 3. Partial answer? → Extend the existing file, then link.")
    print("  □ 4. No answer? → Create new note in quant/arsenal/.")
    print()


def content_parts_to_text(parts: object) -> str:
    if not isinstance(parts, list):
        return ""
    texts: List[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if part.get("type") in {"input_text", "output_text"}:
            text = part.get("text")
            if isinstance(text, str):
                texts.append(text)
    return "\n".join(t for t in texts if t).strip()


def clean_codex_user_text(text: str) -> str:
    # Codex Desktop stores the AGENTS/env bootstrap inside the first user message.
    # For diary transcripts, keep the actual user request and drop the bootstrap.
    marker = "</environment_context>"
    if "# AGENTS.md instructions" in text and marker in text:
        text = text.split(marker, 1)[1].strip()
    if text.startswith("<turn_aborted>"):
        return ""
    return text.strip()


def clean_codex_assistant_text(text: str, keep_memory_citation: bool = False) -> str:
    if not keep_memory_citation:
        text = MEMORY_CITATION_RE.sub("", text)
    return text.strip()


def latest_codex_thread_id() -> str:
    if not CODEX_SESSION_INDEX.exists():
        raise FileNotFoundError(f"Codex session index not found: {CODEX_SESSION_INDEX}")
    latest = ""
    for line in read_text(CODEX_SESSION_INDEX).splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record.get("id"), str):
            latest = record["id"]
    if not latest:
        raise ValueError(f"No thread ids found in {CODEX_SESSION_INDEX}")
    return latest


def codex_session_file_for_thread(thread_id: str) -> Path:
    matches = sorted(CODEX_SESSIONS_DIR.rglob(f"*{thread_id}.jsonl"))
    if not matches:
        raise FileNotFoundError(f"No Codex session jsonl found for thread id: {thread_id}")
    return matches[-1]


def codex_session_files_for_date(d: date) -> List[Path]:
    day_dir = CODEX_SESSIONS_DIR / d.strftime("%Y") / d.strftime("%m") / d.strftime("%d")
    if not day_dir.exists():
        return []
    return sorted(day_dir.glob("*.jsonl"))


def codex_thread_label(session_file: Path) -> str:
    for raw in read_text(session_file).splitlines():
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if record.get("type") == "session_meta":
            payload = record.get("payload")
            if isinstance(payload, dict) and isinstance(payload.get("id"), str):
                return payload["id"]
    m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", session_file.name)
    return m.group(1) if m else session_file.stem


def codex_session_files_for_date_range(d: date) -> List[Path]:
    """Gather candidate Codex JSONL files from d-1, d, and d+1 directories.

    This catches sessions that span midnight.  Per-message timestamp filtering
    in ``export_codex_transcript(target_date=…)`` handles the precise cutoff.
    """
    seen: set = set()
    result: List[Path] = []
    for offset in (-1, 0, 1):
        day = d + timedelta(days=offset)
        for p in codex_session_files_for_date(day):
            if p not in seen:
                seen.add(p)
                result.append(p)
    return result


def export_codex_day_transcript(
    d: date,
    assistant_name: str = "Codex",
    user_name: str = "Henry",
    include_commentary: bool = False,
    keep_memory_citation: bool = False,
) -> str:
    blocks: List[str] = []
    for session_file in codex_session_files_for_date_range(d):
        transcript = export_codex_transcript(
            session_file,
            assistant_name=assistant_name,
            user_name=user_name,
            include_commentary=include_commentary,
            keep_memory_citation=keep_memory_citation,
            target_date=d,
        ).strip()
        if transcript:
            blocks.append(f"### Codex Thread {codex_thread_label(session_file)}\n\n{transcript}")
    return "\n\n".join(blocks).rstrip() + ("\n" if blocks else "")


def export_codex_transcript(
    session_file: Path,
    assistant_name: str = "Codex",
    user_name: str = "Henry",
    include_commentary: bool = False,
    keep_memory_citation: bool = False,
    target_date: Optional[date] = None,
) -> str:
    """Export a Codex session transcript.

    When *target_date* is provided, only records whose timestamp (converted to
    local timezone) matches that date are included.  This lets multi-day
    sessions be sliced into per-day traces.
    """
    lines: List[str] = []
    current_speaker = ""
    current_text = ""
    current_ts = ""

    def flush() -> None:
        nonlocal current_speaker, current_text, current_ts
        text = current_text.strip()
        if text:
            lines.append(f"[{format_chat_timestamp(current_ts)}] {current_speaker}: {text}")
        current_speaker = ""
        current_text = ""
        current_ts = ""

    for raw in read_text(session_file).splitlines():
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if record.get("type") != "response_item":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "message":
            continue
        role = payload.get("role")
        if role not in {"user", "assistant"}:
            continue
        if role == "assistant" and payload.get("phase") == "commentary" and not include_commentary:
            continue
        text = content_parts_to_text(payload.get("content"))
        if role == "user":
            text = clean_codex_user_text(text)
            speaker = user_name
        else:
            text = clean_codex_assistant_text(text, keep_memory_citation=keep_memory_citation)
            speaker = assistant_name
        if not text:
            continue

        ts = str(record.get("timestamp") or "")
        # Per-message date filter: skip records that don't fall on target_date.
        if target_date is not None:
            if not ts or timestamp_to_local_date(ts) != target_date:
                continue

        if speaker == current_speaker and ts == current_ts:
            current_text = f"{current_text}\n\n{text}".strip()
        else:
            flush()
            current_speaker = speaker
            current_text = text
            current_ts = ts
    flush()
    return "\n\n".join(lines).rstrip() + ("\n" if lines else "")


def claudian_meta_files() -> List[Path]:
    if not CLAUDIAN_SESSIONS_DIR.exists():
        return []
    return sorted(CLAUDIAN_SESSIONS_DIR.glob("*.meta.json"))


def claudian_sessions_for_date(d: date) -> List[dict]:
    """Return Claudian session metadata dicts whose provider JSONL exists.

    Uses meta createdAt/updatedAt as a coarse pre-filter but also includes
    sessions whose timestamps don't exactly match d — per-message timestamp
    filtering in export_claudian_day_transcript handles the precise cutoff.
    """
    sessions: List[dict] = []
    for meta_file in claudian_meta_files():
        try:
            meta = json.loads(read_text(meta_file))
        except (json.JSONDecodeError, FileNotFoundError):
            continue
        provider_id = meta.get("providerState", {}).get("providerSessionId")
        if not provider_id:
            continue
        jsonl_path = CLAUDE_PROJECTS_DIR / f"{provider_id}.jsonl"
        if not jsonl_path.exists():
            continue
        # Coarse filter: include if createdAt or updatedAt is within ±1 day of d.
        # Per-message filtering in export handles the exact date match.
        created = meta.get("createdAt")
        updated = meta.get("updatedAt")
        include = False
        for ts_ms in [created, updated]:
            if ts_ms:
                meta_date = datetime.fromtimestamp(ts_ms / 1000).date()
                if abs((meta_date - d).days) <= 1:
                    include = True
                    break
        if include:
            sessions.append(meta)
    return sessions


def export_claudian_day_transcript(d: date, user_name: str = "Henry", assistant_name: str = "Claudian") -> Tuple[str, int, int]:
    """Build a combined transcript of all Claudian sessions for date d.

    Returns (transcript_text, message_count, session_count).
    Only includes messages whose record timestamp falls on d in local timezone.
    """
    sessions = claudian_sessions_for_date(d)
    blocks: List[str] = []
    total_messages = 0
    for meta in sessions:
        provider_id = meta["providerState"]["providerSessionId"]
        title = meta.get("title") or provider_id
        jsonl_path = CLAUDE_PROJECTS_DIR / f"{provider_id}.jsonl"
        if not jsonl_path.exists():
            continue
        lines: List[str] = []
        current_speaker = ""
        current_text = ""
        current_ts = ""

        def flush() -> None:
            nonlocal current_speaker, current_text, current_ts
            text = current_text.strip()
            if text:
                lines.append(f"[{current_ts}] {current_speaker}: {text}")
            current_speaker = ""
            current_text = ""
            current_ts = ""

        for raw in read_text(jsonl_path).splitlines():
            if not raw.strip():
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                continue
            rec_type = record.get("type")
            if rec_type not in ("user", "assistant"):
                continue

            # Date filter: only include messages whose timestamp falls on d.
            ts = str(record.get("timestamp") or "")
            if not ts or timestamp_to_local_date(ts) != d:
                continue

            if rec_type == "user":
                msg = record.get("message", {})
                content = msg.get("content")
                if isinstance(content, str):
                    text = content.strip()
                elif isinstance(content, list):
                    text_parts = [
                        p.get("text", "")
                        for p in content
                        if isinstance(p, dict) and p.get("type") == "input_text" and p.get("text")
                    ]
                    text = "\n".join(text_parts).strip()
                else:
                    continue
                if not text:
                    continue
                speaker = user_name
            else:
                msg = record.get("message", {})
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                text_parts = [
                    p.get("text", "")
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text" and p.get("text")
                ]
                text = "\n".join(text_parts).strip()
                if not text:
                    continue
                speaker = assistant_name

            formatted_ts = format_chat_timestamp(ts)
            if speaker == current_speaker and formatted_ts == current_ts:
                current_text = f"{current_text}\n\n{text}".strip()
            else:
                flush()
                current_speaker = speaker
                current_text = text
                current_ts = formatted_ts
        flush()
        if lines:
            total_messages += len(lines)
            blocks.append(f"### Claudian Session {provider_id} - {title}\n\n" + "\n\n".join(lines))
    return "\n\n".join(blocks).rstrip() + ("\n" if blocks else ""), total_messages, len(blocks)


def load_life_claude_renderer_history(history_path: Path) -> List[dict]:
    """Load conversations from the plugin's history.json.

    Returns an empty list when the file is missing or malformed.
    Validates conservatively: top-level must be a JSON array, each element
    must have sessionId (string) and messages (list).
    Never modifies the source file.
    """
    if not history_path.exists():
        return []
    try:
        raw = read_text(history_path)
        parsed = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(parsed, list):
        return []
    result: List[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        sid = item.get("sessionId")
        msgs = item.get("messages")
        if not isinstance(sid, str) or not isinstance(msgs, list):
            continue
        result.append(item)
    return result


def export_life_claude_renderer_day_transcript(
    d: date,
    history_path: Optional[Path] = None,
    user_name: str = "Henry",
    assistant_name: str = "Claude",
) -> Tuple[str, int, int]:
    """Build a combined transcript of all Life Claude Renderer sessions for date d.

    Returns (transcript_text, message_count, session_count).
    Only includes messages whose millisecond timestamp falls on d in local timezone.
    A conversation spanning several dates is sliced per message date.
    Sessions are sorted by their earliest included message timestamp.
    """
    if history_path is None:
        history_path = LIFE_CLAUDE_RENDERER_HISTORY
    conversations = load_life_claude_renderer_history(history_path)

    session_blocks: List[Tuple[float, str]] = []  # (earliest_ts, block_text)
    total_messages = 0

    for conv in conversations:
        sid = conv.get("sessionId", "")
        title = conv.get("title") or sid
        messages = conv.get("messages", [])
        if not isinstance(messages, list):
            continue

        lines: List[str] = []
        earliest_ts: Optional[float] = None

        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            if role not in ("user", "assistant"):
                continue
            ts_ms = msg.get("timestamp")
            if not isinstance(ts_ms, (int, float)):
                continue
            # Per-message date filter
            msg_date = datetime.fromtimestamp(ts_ms / 1000).date()
            if msg_date != d:
                continue

            if role == "user":
                text = msg.get("displayContent") or msg.get("content") or ""
            else:
                text = msg.get("content") or ""
            if not isinstance(text, str) or not text.strip():
                continue

            # Append image attachment provenance for user messages
            if role == "user":
                attachments = msg.get("contextAttachments") or []
                image_lines = []
                for att in attachments:
                    if not isinstance(att, dict) or att.get("type") != "image":
                        continue
                    att_path = att.get("path", "")
                    att_mime = att.get("mime", "")
                    att_size = att.get("sizeBytes")
                    parts = [f"path={att_path}"]
                    if att_mime:
                        parts.append(f"mime={att_mime}")
                    if att_size is not None:
                        parts.append(f"size={att_size} bytes")
                    image_lines.append(f"  - Image: {', '.join(parts)}")
                if image_lines:
                    text = text.rstrip() + "\n\nAttachments:\n" + "\n".join(image_lines)

            if earliest_ts is None or ts_ms < earliest_ts:
                earliest_ts = ts_ms

            formatted_ts = format_chat_timestamp(
                datetime.fromtimestamp(ts_ms / 1000).isoformat()
            )
            speaker = user_name if role == "user" else assistant_name
            lines.append(f"[{formatted_ts}] {speaker}: {text.strip()}")

        if lines and earliest_ts is not None:
            total_messages += len(lines)
            block = f"### Life Claude Renderer Session {sid} - {title}\n\n" + "\n\n".join(lines)
            session_blocks.append((earliest_ts, block))

    # Sort by earliest included message timestamp
    session_blocks.sort(key=lambda x: x[0])
    blocks = [block for _, block in session_blocks]
    return "\n\n".join(blocks).rstrip() + ("\n" if blocks else ""), total_messages, len(blocks)


def split_markdown_sections(text: str) -> List[Tuple[str, str]]:
    lines = text.splitlines()
    sections: List[Tuple[str, str]] = []
    heading = ""
    buf: List[str] = []
    for line in lines:
        if line.startswith("## "):
            if heading or buf:
                sections.append((heading, "\n".join(buf).strip()))
            heading = line[3:].strip()
            buf = []
        else:
            buf.append(line)
    if heading or buf:
        sections.append((heading, "\n".join(buf).strip()))
    return sections


def summarize_open_xp(max_items: int = 6) -> List[Tuple[str, str]]:
    if not ROADMAP_FILE.exists():
        return []
    out: List[Tuple[str, str]] = []
    for line in read_text(ROADMAP_FILE).splitlines():
        m = XP_OPEN_RE.match(line.strip())
        if m:
            out.append((m.group(1), m.group(2)))
            if len(out) >= max_items:
                break
    return out


def extract_quant_feedback(journal_text: str) -> Dict[str, str]:
    lines = journal_text.splitlines()
    start = end = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("## 📊 Legacy Quant Feedback") or stripped.startswith("## 📊 Quant Protocol Feedback"):
            start = i
        elif start is not None and i > start and stripped.startswith("## "):
            end = i
            break
    if start is None:
        return {}
    section = "\n".join(lines[start : end or len(lines)])

    def find(pattern: str) -> str:
        m = re.search(pattern, section, re.IGNORECASE)
        val = m.group(1).strip() if m else ""
        if "___%" in val or "High/Low" in val or "e.g." in val:
            return ""
        return val

    return {
        "morning_score": find(r"Morning Block:[ \t]*`?([^`\n]+)`?"),
        "afternoon_score": find(r"Afternoon Block:[ \t]*`?([^`\n]+)`?"),
        "evening_score": find(r"Evening Block:[ \t]*`?([^`\n]+)`?"),
        "roadblocks": find(r"\*{0,2}Roadblocks\*{0,2}:[ \t]*([^\n]*)"),
        "energy": find(r"\*{0,2}Energy Level \(AM/PM/Eve\)\*{0,2}:[ \t]*`?([^`\n]+)`?"),
        "tomorrow_request": find(r"\*{0,2}Request for Tomorrow\*{0,2}:[ \t]*([^\n]*)"),
    }


def has_filled_quant_feedback(journal_text: str) -> bool:
    # The section title alone is not enough. We only treat Legacy Quant Feedback
    # as "filled" when at least one Quant-specific execution field contains a real
    # value rather than template placeholders such as ___%, High/Low, or empty strings.
    # tomorrow_request alone does NOT qualify — it is a general life planning hint,
    # not evidence of Quant execution feedback. It can only contribute after at least
    # one execution field (morning/afternoon/evening scores, roadblocks, energy) passes.
    fb = extract_quant_feedback(journal_text)
    execution_fields = ["morning_score", "afternoon_score", "evening_score", "roadblocks", "energy"]
    has_execution = any(bool(fb.get(f, "").strip()) for f in execution_fields)
    if not has_execution:
        return False
    return True


# ---------------------------------------------------------------------------
# Quant state load/save
# ---------------------------------------------------------------------------
def load_quant_state() -> Dict[str, List[str] | str]:
    if not QUANT_STATE_FILE.exists():
        return {"last_updated": "", "current_focus": "", "schedule_hints": [], "pending_xp": [], "evidence_log": []}
    text = read_text(QUANT_STATE_FILE)

    def get_single(label: str) -> str:
        m = re.search(rf"- {re.escape(label)}:\s*(.+)", text)
        return m.group(1).strip() if m else ""

    def get_list(section: str) -> List[str]:
        m = re.search(rf"## {re.escape(section)}\n(.*?)(?:\n## |\Z)", text, re.DOTALL)
        if not m:
            return []
        return [ln[2:].strip() for ln in m.group(1).splitlines() if ln.strip().startswith("- ")]

    return {
        "last_updated": get_single("last_updated"),
        "current_focus": get_single("current_focus"),
        "schedule_hints": get_list("Schedule Hints"),
        "pending_xp": get_list("Pending XP"),
        "evidence_log": get_list("Evidence Log"),
    }


def save_quant_state(payload: Dict[str, List[str] | str]) -> None:
    lines = [
        "# Quant State", "",
        "## Metadata",
        f"- last_updated: {payload.get('last_updated', '')}",
        f"- current_focus: {payload.get('current_focus', '')}",
        "",
        "## Schedule Hints",
    ]
    for item in payload.get("schedule_hints", []) or ["(none)"]:
        lines.append(f"- {item}")
    lines += ["", "## Pending XP"]
    for item in payload.get("pending_xp", []) or ["(none)"]:
        lines.append(f"- {item}")
    lines += ["", "## Evidence Log"]
    for item in payload.get("evidence_log", []) or ["(none)"]:
        lines.append(f"- {item}")
    lines += [
        "", "## Source Policy",
        "- Primary: structured quant section in daily journal.",
        "- Secondary: direct chat updates only when explicitly confirmed.",
        "- Tertiary: objective outputs under quant/.", "",
    ]
    write_text(QUANT_STATE_FILE, "\n".join(lines))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_sync_quant_state(args: argparse.Namespace) -> None:
    state = load_quant_state()
    today = parse_date_str(args.date)
    hints: List[str] = [h for h in state.get("schedule_hints", []) if h and h != "(none)"]  # type: ignore
    evidence: List[str] = [e for e in state.get("evidence_log", []) if e and e != "(none)"]  # type: ignore
    pending = [f"{xp}: {task}" for xp, task in summarize_open_xp(6)]
    focus_items = [xp for xp, _ in summarize_open_xp(3)]
    focus = ", ".join(focus_items) if focus_items else "no pending XP; refer to life-board.md"

    journal_path = journal_path_for_date(today)
    if journal_path.exists():
        journal_text = read_text(journal_path)
        fb = extract_quant_feedback(journal_text)
        has_feedback = has_filled_quant_feedback(journal_text)
        # Date-based sync is gated by filled journal feedback. Manual chat-note
        # overrides stay available because they are an explicit secondary source.
        if not has_feedback and not args.chat_note:
            print(f"[skip] Filled Legacy Quant Feedback not found in {journal_path}; quant state not updated.")
            return
        if has_feedback:
            if fb.get("tomorrow_request"):
                hints.insert(0, f"tomorrow_request={fb['tomorrow_request']}")
            if fb.get("roadblocks"):
                hints.insert(0, f"roadblocks={fb['roadblocks']}")
            scores = ", ".join(x for x in [fb.get("morning_score"), fb.get("afternoon_score"), fb.get("evening_score")] if x)
            evidence.insert(0, f"[{today}] journal={journal_path.relative_to(ROOT)} scores={scores or 'n/a'}")
    elif args.allow_missing_journal:
        if not args.chat_note:
            print(f"[skip] Journal not found for {today.isoformat()} and no chat note provided; quant state not updated.")
            return
        evidence.insert(0, f"[{today}] journal=missing (allowed)")
    else:
        raise FileNotFoundError(f"Journal not found: {journal_path}")

    if args.chat_note:
        hints.insert(0, f"chat_note={args.chat_note}")
        evidence.insert(0, f"[{today}] chat_note={args.chat_note}")

    # Dedup hints
    seen: set = set()
    dedup_hints = [h for h in hints if h and h not in seen and not seen.add(h)]  # type: ignore

    # Dedup evidence by date
    ev_by_date: dict[str, str] = {}
    ev_order: list[str] = []
    for e in evidence:
        m = re.match(r"\[(\d{4}-\d{2}-\d{2})\]", e)
        key = m.group(1) if m else e
        if key not in ev_by_date:
            ev_by_date[key] = e
            ev_order.append(key)
        else:
            old_nums = len(re.findall(r"\d+", ev_by_date[key].split("scores=")[-1])) if "scores=" in ev_by_date[key] else 0
            new_nums = len(re.findall(r"\d+", e.split("scores=")[-1])) if "scores=" in e else 0
            if new_nums > old_nums:
                ev_by_date[key] = e

    payload = {
        "last_updated": today.isoformat(),
        "current_focus": focus,
        "schedule_hints": dedup_hints[:12],
        "pending_xp": pending,
        "evidence_log": [ev_by_date[k] for k in ev_order][:30],
    }
    save_quant_state(payload)
    print(str(QUANT_STATE_FILE))



def cmd_update_schedule(args: argparse.Namespace) -> None:
    if not ROADMAP_FILE.exists():
        raise FileNotFoundError(f"Roadmap not found: {ROADMAP_FILE}")

    if getattr(args, "target_date", None):
        target = parse_date_str(args.target_date)
        base = target - timedelta(days=1)
    else:
        base = parse_date_str(args.date)
        target = base + timedelta(days=1)
        journal_path = journal_path_for_date(base)
        # Date-based schedule refresh only happens when today's journal contains
        # filled Legacy Quant Feedback. Use --target-date for an explicit manual
        # schedule generation / repoint path.
        if not journal_path.exists():
            print(f"[skip] Journal not found for {base.isoformat()}; schedule not updated.")
            return
        if not has_filled_quant_feedback(read_text(journal_path)):
            print(f"[skip] Filled Legacy Quant Feedback not found in {journal_path}; schedule not updated.")
            return

    roadmap_content = read_text(ROADMAP_FILE)
    schedule_path = _schedule_file_path(target)
    schedule_body = build_active_schedule_block(base)
    schedule_path.parent.mkdir(parents=True, exist_ok=True)

    # Schedule files are generated artifacts. Rebuild them on every run so a later
    # journal writeback or quant-state sync can refresh tomorrow's plan instead of
    # getting stuck behind an existing file from an earlier pass.
    if not schedule_path.exists() or read_text(schedule_path) != schedule_body:
        write_text(schedule_path, schedule_body)

    updated_roadmap = _update_roadmap_pointer(roadmap_content, target)
    if updated_roadmap != roadmap_content:
        write_text(ROADMAP_FILE, updated_roadmap)

    print(str(schedule_path))


def _schedule_file_path(d: date) -> Path:
    return SCHEDULES_DIR / d.strftime("%Y") / d.strftime("%m") / f"sched-{d.isoformat()}.md"


def _extract_schedule_date(content: str) -> Optional[date]:
    m = re.search(r"\*Current:\s*\[\[(?:sched-)?(\d{4}-\d{2}-\d{2})\]\]\s*\*", content)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            pass
    m2 = re.search(r"## ⚡️ (?:Legacy Quant Schedule|Active Schedule):.*?(\w+), (\w+) (\d+), (\d{4})", content)
    if m2:
        try:
            return datetime.strptime(f"{m2.group(2)} {m2.group(3)} {m2.group(4)}", "%b %d %Y").date()
        except ValueError:
            pass
    return None


def _detect_schedule_phase(
    tomorrow_request: str,
    roadblocks: str,
    pending: List[str],
    focus: str,
) -> str:
    """Determine the schedule phase from available signals."""
    tr_lower = tomorrow_request.lower()
    rb_lower = roadblocks.lower()
    focus_lower = focus.lower()
    combined = f"{tr_lower} {rb_lower} {focus_lower}"

    # Explicit phase keywords in tomorrow_request or focus
    for phase in PHASE_PROTOCOLS:
        if phase.lower() in combined:
            return phase

    # Heuristic: no pending XP and no request → recovery or review
    if not pending and not tomorrow_request.strip():
        return "Recovery"

    # Default: if there are pending items, assume Build
    if pending:
        return "Build"

    return "Review"


def build_active_schedule_block(base_date: date) -> str:
    target = base_date + timedelta(days=1)
    state = load_quant_state()
    pending = [p for p in state.get("pending_xp", []) if isinstance(p, str) and p and p != "(none)"]
    focus = state.get("current_focus", "quant execution")
    hints = [h for h in state.get("schedule_hints", []) if isinstance(h, str)]

    fb = extract_quant_feedback(read_text(journal_path_for_date(base_date))) if journal_path_for_date(base_date).exists() else {}
    tr = fb.get("tomorrow_request") or next((h.split("=", 1)[1] for h in hints if h.startswith("tomorrow_request=")), "")
    rb = fb.get("roadblocks") or next((h.split("=", 1)[1] for h in hints if h.startswith("roadblocks=")), "")
    requested_ids = list(dict.fromkeys(re.findall(r"XP-\d+", tr.upper())))
    requested_targets = []
    for xp_id in requested_ids:
        match = next((p for p in pending if p.upper().startswith(f"{xp_id}:")), "")
        requested_targets.append(match or xp_id)

    if requested_targets:
        remaining = [p for p in pending if p not in requested_targets]
        top = (requested_targets + remaining)[:4]
        focus = ", ".join(requested_ids)
    else:
        top = pending[:4]

    phase = _detect_schedule_phase(tr, rb, pending, focus)
    phase_protocol = PHASE_PROTOCOLS.get(phase, PHASE_PROTOCOLS["Build"])

    weekday = target.strftime("%A")
    date_label = target.strftime("%b %-d, %Y") if os.name != "nt" else target.strftime("%b %#d, %Y")
    xp_targets = focus
    xp_morning = top[0] if top else "No pending tasks — use for review or exploration."
    xp_afternoon = top[1] if len(top) > 1 else xp_morning
    personal_action_1 = tr if tr else "Keep Agency Time flexible for recovery or side exploration."
    personal_action_2 = "Do not turn Agency Time into a scored execution block."
    execution_intent = (
        "If afternoon energy drops, protect Deep Work A and B first, then let Agency Time absorb sports or recovery."
    )

    if SCHED_LIBRARY_DAY_TEMPLATE.exists():
        template = read_text(SCHED_LIBRARY_DAY_TEMPLATE)
        replacements = {
            "{{weekday}}": weekday,
            "{{date}}": date_label,
            "{{xp-targets}}": xp_targets,
            "{{phase-protocol}}": f"[{phase}] {phase_protocol}",
            "{{yesterday-request}}": tr if tr else "(none)",
            "{{yesterday-roadblocks}}": rb if rb else "(none)",
            "{{xp-morning}}": xp_morning,
            "{{xp-afternoon}}": xp_afternoon,
            "{{personal-action-1}}": personal_action_1,
            "{{personal-action-2}}": personal_action_2,
            "{{execution-intent}}": execution_intent,
        }
        for key, value in replacements.items():
            template = template.replace(key, value)
        return template

    target_ids = ", ".join(t.split(":")[0] for t in top[:3]) if top else "(none)"
    b = [
        f"## ⚡️ Legacy Quant Schedule: {format_day_label(target)}",
        f"*Focus: {focus}*", "",
        f"> **Current Phase**: **[{phase}]** {phase_protocol}",
        f"> **Target**: {target_ids}.",
        f"> **Context Hint**: Yesterday's request: {tr if tr else '(none)'}; Roadblocks: {rb if rb else '(none)'}.", "",
        "> _Legacy Quant schedule — not the v4.3 default projection. Adjust based on actual energy and events._", "",
        "| Time | Block Name | Target Task |",
        "| :--- | :--------- | :---------- |",
        "| **07:30 - 08:30** | **🌅 Morning Routine** | Wake, hygiene, ride to library. |",
        f"| **08:30 - 12:00** | **⚔️ Deep Work A** | {xp_morning}. |",
        "| **12:00 - 13:00** | **🍲 Lunch** | Fixed Time Anchor. |",
        "| **13:00 - 14:00** | **💤 Power Nap** | Non-negotiable Recovery. |",
        f"| **14:00 - 17:00** | **⚔️ Deep Work B** | {xp_afternoon}. |",
        "| **17:00 - 18:00** | **🍲 Dinner** | Fixed Time Anchor. |",
        "| **18:00 - 22:00** | **🕹️ Agency Time** | Free-choice block: sports / reading / social / casual exploration. No execution score applied. |",
        "| **22:00 - 22:30** | **📔 Reflection** | Daily log + tomorrow projection input. |",
        "| **22:30 - 23:00** | **🛌 Wind Down** | No screens. |",
        "| **23:00** | **💤 Sleep** | System Shutdown. |",
    ]
    return "\n".join(b) + "\n"


def _update_roadmap_pointer(roadmap_content: str, target: date) -> str:
    rel = _schedule_file_path(target).relative_to(ROOT)
    new_pointer = (
        f"## ⚡️ Active Schedule\n"
        f"*Current: [[sched-{target.isoformat()}]] * → `{rel}`\n\n"
        f"> 日程文件统一管理于 `quant/schedules/YYYY/MM/sched-YYYY-MM-DD.md`，此处只保留指针。\n\n---"
    )
    m = re.search(r"## ⚡️ Active Schedule\b.*?(?=^## |\Z)", roadmap_content, re.DOTALL | re.MULTILINE)
    if m:
        return roadmap_content[: m.start()] + new_pointer + "\n\n" + roadmap_content[m.end() :]
    return roadmap_content


# --- Quant mission / note / summary ---

def render_quant_mission(xp_id: str, xp_task: str, d: date) -> str:
    task_text = xp_task or "Define concrete objective before execution."
    state = load_quant_state()
    focus = str(state.get("current_focus", "")).strip() or "Quant execution"
    hints = [h for h in state.get("schedule_hints", []) if isinstance(h, str)]
    return "\n".join([
        f"# ⚔️ {xp_id} Mission Guide", "",
        "## Meta",
        f"- date: {d.isoformat()}", f"- xp: {xp_id}", f"- task: {task_text}",
        f"- focus: {focus}", f"- hint: {hints[0] if hints else 'No extra hint.'}", "",
        "## Inputs",
        "- `quant/state.md`", "- `quant/roadmap.md`", "",
        "## Mission Guide Payload",
        f"<!-- AI_FILL: Generate a teaching-oriented mission guide for this XP.",
        f"    Task: {task_text}",
        "    Follow the Learning Collaboration Protocol in prompts/quant-mode.md.",
        "    Classify as THEORY / CODE / HYBRID and generate accordingly.",
        "    Replace this block with your generated content. -->", "",
        "## Question Links",
        "<!-- AI_FILL: After generating the mission guide, collect reusable learning",
        "    questions as bullet-point wikilinks here. Use [[target#heading|question]]",
        "    format. Run: python3 scripts/copilot.py quant-question-link --question \"...\"",
        "    to search existing files before creating new link targets. -->", "",
    ])



def cmd_quant_mission(args: argparse.Namespace) -> None:
    QUANT_ARSENAL_DIR.mkdir(parents=True, exist_ok=True)
    d = parse_date_or_today(args.date)
    xp_id = normalize_xp_id(args.xp)
    tag = find_xp_tag(xp_id)
    if tag == "course" and not args.force:
        print(f"[skip] {xp_id} is tagged #course — mission guide not needed. Use --force to override.")
        return
    out = quant_mission_file(xp_id)
    if out.exists() and not args.force:
        print(str(out))
        return
    write_text(out, render_quant_mission(xp_id, find_xp_task(xp_id), d).rstrip() + "\n")
    print(str(out))



# --- Writeback commands ---

def looks_like_copilot_analysis(content: str) -> bool:
    """Best-effort guardrail for routing analysis to writeback-journal.

    Old diary analyses used fixed section headings; diary-mode v2 is essay-first,
    so we now combine explicit marker checks with a small heuristic to catch
    obvious Copilot analysis while avoiding over-blocking normal journal thoughts.
    """
    text = content.strip()
    if not text:
        return False

    explicit_markers = [
        "## What Life Copilot Said",
        "## 🌡️ 情绪与能量状态",
        "## 🧠 深度洞察",
        "## 🧭 Copilot 建议",
        "## ❓ 深度追问",
        "## 💾 记忆更新",
        "## 📊 进展追踪",
        "## 🔇 沉默议题提醒",
    ]
    if any(marker in text for marker in explicit_markers):
        return True

    heuristic_score = 0

    if re.search(r"\[\[\d{4}-\d{2}-\d{2}\]\]", text):
        heuristic_score += 1
    if text.count("你") >= 3:
        heuristic_score += 1

    analysis_cues = [
        "主线",
        "盲区",
        "未言明需求",
        "证据不足",
        "Writing State",
        "历史锚点",
        "反框架",
        "红队",
        "长期记忆",
        "Quant Mode",
    ]
    if any(cue in text for cue in analysis_cues):
        heuristic_score += 1

    action_cues = [
        "微行动",
        "明天最值得做的",
        "明天 24 小时内",
        "我会建议",
        "如果今天要沉淀一条长期记忆",
        "建议进入 Quant Mode",
    ]
    if any(cue in text for cue in action_cues):
        heuristic_score += 1

    return heuristic_score >= 3


def append_thought_to_journal(journal_text: str, title: str, content: str) -> str:
    # Guardrail: this command is for writing user-side diary thoughts,
    # not for writing Copilot analysis into the journal body.
    if looks_like_copilot_analysis(content):
        raise ValueError("Input looks like Copilot analysis. Use writeback-journal instead of writeback-thought.")

    lines = journal_text.splitlines(keepends=True)

    def section_bounds(fragment: str):
        start = end = None
        for i, line in enumerate(lines):
            if start is None and fragment in line and line.startswith("##"):
                start = i
            elif start is not None and line.startswith("## "):
                end = i
                break
        return start, end or len(lines)

    thought_block = f"\n'{title}'\n\n{content.strip()}\n"

    tr_start, tr_end = section_bounds("Thoughts & Reflections")
    if tr_start is None:
        raise ValueError("Section '💭 Thoughts & Reflections' not found in journal")
    i = tr_end - 1
    while i > tr_start and lines[i].strip() == "":
        i -= 1
    lines.insert(i + 1, thought_block)

    return "".join(lines)


def cmd_writeback_thought(args: argparse.Namespace) -> None:
    target = parse_date_str(args.date)
    jp = journal_path_for_date(target)
    if not jp.exists():
        raise FileNotFoundError(f"Journal not found: {jp}")
    if not args.input_file:
        raise ValueError("--input-file is required")
    write_text(jp, append_thought_to_journal(read_text(jp), args.title, read_text(Path(args.input_file))))
    print(str(jp))


def replace_journal_copilot_section(journal_text: str, new_section: str) -> str:
    marker = "## What Life Copilot Said"
    idx = journal_text.find(marker)
    if idx == -1:
        raise ValueError(f"marker not found: {marker}")
    
    after_marker = journal_text[idx + len(marker):]
    next_h2 = re.search(r"(?m)^## ", after_marker)
    tail = after_marker[next_h2.start():] if next_h2 else ""
    
    new_stripped = new_section.strip()
    if new_stripped.startswith(marker):
        new_stripped = new_stripped[len(marker):].strip()
    
    return journal_text[: idx + len(marker)].rstrip() + "\n\n" + new_stripped + ("\n\n" + tail if tail else "\n")


def append_journal_section(journal_text: str, marker: str, addition: str, replace: bool = False) -> str:
    idx = journal_text.find(marker)
    if idx == -1:
        raise ValueError(f"marker not found: {marker}")

    body_start = idx + len(marker)
    after_marker = journal_text[body_start:]
    next_h2 = re.search(r"(?m)^## ", after_marker)
    body_end = body_start + next_h2.start() if next_h2 else len(journal_text)
    before = journal_text[:body_start].rstrip()
    existing = journal_text[body_start:body_end].strip()
    tail = journal_text[body_end:]
    new_addition = addition.strip()

    if replace or not existing:
        new_body = new_addition
    else:
        new_body = existing.rstrip() + "\n\n" + new_addition

    return before + "\n\n" + new_body.rstrip() + ("\n\n" + tail.lstrip("\n") if tail else "\n")


def render_diary_from_template(target_date: date) -> str:
    """Create a diary from the daily-log template for *target_date*.

    The template no longer contains a creation-time field. The {{time:HH:mm}}
    replacement is kept as a harmless no-op for backward compatibility with
    older template copies that still carry the placeholder.
    """
    template_path = TEMPLATES_DIR / "daily-log.md"
    template = read_text(template_path)
    rendered = template.replace("{{date:YYYY-MM-DD}}", target_date.isoformat())
    rendered = rendered.replace("{{time:HH:mm}}", "")
    return rendered


def write_daily_suggestion(
    journal_text: str,
    content: str,
    source_date: date,
    force: bool = False,
) -> str:
    """Write or update the ``## 🧭 Daily Suggestion`` section.

    Idempotent: re-running with the same *source_date* replaces the body.
    Refuses to overwrite when the section already holds content from a
    different source unless *force* is True.
    """
    marker = "## 🧭 Daily Suggestion"
    provenance = f"> Generated from [[{source_date.isoformat()}]] diary analysis."
    block = f"{provenance}\n\n{content.strip()}"

    if marker in journal_text:
        idx = journal_text.find(marker)
        body_start = idx + len(marker)
        after = journal_text[body_start:]
        next_h2 = re.search(r"(?m)^## ", after)
        body_end = body_start + next_h2.start() if next_h2 else len(journal_text)
        existing = journal_text[body_start:body_end].strip()

        if existing:
            existing_source = re.search(
                r"> Generated from \[\[(\d{4}-\d{2}-\d{2})\]\]", existing
            )
            if existing_source:
                if existing_source.group(1) == source_date.isoformat():
                    # Same source — replace body (idempotent re-run).
                    return (
                        journal_text[:body_start].rstrip()
                        + "\n\n"
                        + block
                        + "\n"
                        + journal_text[body_end:]
                    )
                # Different source
                if not force:
                    raise ValueError(
                        f"Daily Suggestion already has content from "
                        f"{existing_source.group(1)}. Use --force to overwrite."
                    )
            elif not force:
                raise ValueError(
                    "Daily Suggestion contains content without provenance. "
                    "Use --force to overwrite."
                )
        # Replace body (empty section or forced overwrite).
        return (
            journal_text[:body_start].rstrip()
            + "\n\n"
            + block
            + "\n"
            + journal_text[body_end:]
        )

    # Section does not exist — insert before Thoughts & Reflections if present.
    tr_idx = journal_text.find("## 💭 Thoughts & Reflections")
    if tr_idx != -1:
        return (
            journal_text[:tr_idx].rstrip()
            + "\n\n"
            + marker
            + "\n\n"
            + block
            + "\n\n"
            + journal_text[tr_idx:]
        )
    # No Thoughts section either — append at end.
    return journal_text.rstrip() + "\n\n" + marker + "\n\n" + block + "\n"


def cmd_writeback_daily_suggestion(args: argparse.Namespace) -> None:
    source_date = parse_date_str(args.source_date)
    target_date = source_date + timedelta(days=1)
    input_path = Path(args.input_file)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")
    content = read_text(input_path).strip()
    if not content:
        raise ValueError("Input file is empty")

    jp = journal_path_for_date(target_date)
    journal_text = read_text(jp) if jp.exists() else render_diary_from_template(target_date)
    updated = write_daily_suggestion(journal_text, content, source_date, force=args.force)
    write_text(jp, updated)
    print(str(jp))


def filter_existing_h3_blocks(existing: str, addition: str) -> str:
    blocks = re.split(r"(?m)(?=^### )", addition.strip())
    kept: List[str] = []
    for block in blocks:
        stripped = block.strip()
        if not stripped:
            continue
        first_line = stripped.splitlines()[0].strip()
        if first_line.startswith("### ") and first_line in existing:
            continue
        kept.append(stripped)
    return "\n\n".join(kept).strip()


def cmd_writeback_journal(args: argparse.Namespace) -> None:
    target = parse_date_str(args.date)
    jp = journal_path_for_date(target)
    if not jp.exists():
        raise FileNotFoundError(f"Journal not found: {jp}")
    if not args.input_file:
        raise ValueError("--input-file is required")
    write_text(jp, replace_journal_copilot_section(read_text(jp), read_text(Path(args.input_file))))
    print(str(jp))


def cmd_writeback_codex_thread(args: argparse.Namespace) -> None:
    target = parse_date_str(args.date)
    jp = journal_path_for_date(target)
    if not jp.exists():
        raise FileNotFoundError(f"Journal not found: {jp}")

    if args.session_file:
        session_file = Path(args.session_file).expanduser()
        thread_label = session_file.stem
    else:
        thread_id = args.thread_id or latest_codex_thread_id()
        session_file = codex_session_file_for_thread(thread_id)
        thread_label = thread_id
    transcript = export_codex_transcript(
        session_file,
        assistant_name=args.assistant_name,
        user_name=args.user_name,
        include_commentary=args.include_commentary,
        keep_memory_citation=args.keep_memory_citation,
    ).strip()
    if not transcript:
        raise ValueError(f"No user/assistant transcript messages found in {session_file}")

    heading = args.heading or f"Codex Thread {thread_label}"
    addition = f"### {heading}\n\n{transcript}"
    journal_text = read_text(jp)
    if not args.replace:
        existing = journal_text[journal_text.find("## 💬 From Kai"):]
        addition = filter_existing_h3_blocks(existing, addition)
        if not addition:
            print(str(jp))
            return
    write_text(jp, append_journal_section(journal_text, "## 💬 From Kai", addition, replace=args.replace))
    print(str(jp))


def cmd_writeback_codex_day(args: argparse.Namespace) -> None:
    target = parse_date_str(args.date)
    jp = journal_path_for_date(target)
    if not jp.exists():
        raise FileNotFoundError(f"Journal not found: {jp}")
    transcript = export_codex_day_transcript(
        target,
        assistant_name=args.assistant_name,
        user_name=args.user_name,
        include_commentary=args.include_commentary,
        keep_memory_citation=args.keep_memory_citation,
    ).strip()
    if not transcript:
        raise ValueError(f"No Codex transcript messages found for date: {target.isoformat()}")
    addition = transcript
    if args.heading:
        addition = f"### {args.heading}\n\n{transcript}"
    journal_text = read_text(jp)
    if not args.replace:
        existing = journal_text[journal_text.find("## 💬 From Kai"):]
        addition = filter_existing_h3_blocks(existing, addition)
        if not addition:
            print(str(jp))
            return
    write_text(jp, append_journal_section(journal_text, "## 💬 From Kai", addition, replace=args.replace))
    print(str(jp))


def cmd_preview_ai_day(args: argparse.Namespace) -> None:
    target = parse_date_str(args.date)
    jp = journal_path_for_date(target)

    codex_transcript = export_codex_day_transcript(target).strip()
    codex_msg_count = codex_transcript.count("\n[") + (1 if codex_transcript.startswith("[") else 0) if codex_transcript else 0
    codex_session_count = codex_transcript.count("### Codex Thread ") if codex_transcript else 0

    renderer_transcript, renderer_msg_count, renderer_session_count = export_life_claude_renderer_day_transcript(target)

    codex_path = ai_trace_path_for_date(target, "codex")
    renderer_path = ai_trace_path_for_date(target, "life-claude-renderer")
    codex_link = obsidian_wikilink_for_path(codex_path)
    renderer_link = obsidian_wikilink_for_path(renderer_path)

    print(f"=== AI Day Preview: {target.isoformat()} ===")
    print()

    if codex_transcript:
        print(f"  Codex trace file:                {codex_path.relative_to(ROOT)}")
        print(f"  Codex sessions:                  {codex_session_count}")
        print(f"  Codex messages:                  {codex_msg_count}")
        print(f"  Journal wikilink:                - {codex_link}：Life Copilot / planning / reflection conversations.")
    else:
        print("  Codex:                           (no messages for this date)")

    print()

    if renderer_transcript:
        print(f"  Life Claude Renderer trace file: {renderer_path.relative_to(ROOT)}")
        print(f"  Life Claude Renderer sessions:   {renderer_session_count}")
        print(f"  Life Claude Renderer messages:   {renderer_msg_count}")
        print(f"  Journal wikilink:                - {renderer_link}：Obsidian-rendered Claude Code conversations.")
    else:
        print("  Life Claude Renderer:            (no sessions for this date)")

    print()

    if jp.exists():
        print(f"  Journal file:                    {jp.relative_to(ROOT)} (exists)")
    else:
        print(f"  Journal file:                    {jp.relative_to(ROOT)} (NOT FOUND — writeback will skip)")

    if not codex_transcript and not renderer_transcript:
        print("\n  No AI conversations found for this date.")


def cmd_writeback_ai_day(args: argparse.Namespace) -> None:
    target = parse_date_str(args.date)
    jp = journal_path_for_date(target)
    if not jp.exists():
        raise FileNotFoundError(f"Journal not found: {jp}")

    codex_transcript = export_codex_day_transcript(target).strip()
    renderer_transcript, _, _ = export_life_claude_renderer_day_transcript(target)

    if not codex_transcript and not renderer_transcript:
        raise ValueError(f"No AI conversations (Codex or Life Claude Renderer) found for date: {target.isoformat()}")

    codex_path = ai_trace_path_for_date(target, "codex")
    renderer_path = ai_trace_path_for_date(target, "life-claude-renderer")
    codex_link = obsidian_wikilink_for_path(codex_path)
    renderer_link = obsidian_wikilink_for_path(renderer_path)

    # Write Codex trace file
    if codex_transcript:
        codex_content = "\n".join([
            "---",
            f"date: {target.isoformat()}",
            "source: codex",
            "generated_by: scripts/copilot.py writeback-ai-day",
            "---",
            "",
            f"# {target.isoformat()} Codex Trace",
            "",
            codex_transcript,
        ])
        write_text(codex_path, codex_content)
        print(f"  wrote: {codex_path.relative_to(ROOT)}")

    # Write Life Claude Renderer trace file
    if renderer_transcript:
        renderer_content = "\n".join([
            "---",
            f"date: {target.isoformat()}",
            "source: life-claude-renderer",
            "generated_by: scripts/copilot.py writeback-ai-day",
            "---",
            "",
            f"# {target.isoformat()} Life Claude Renderer Trace",
            "",
            renderer_transcript,
        ])
        write_text(renderer_path, renderer_content)
        print(f"  wrote: {renderer_path.relative_to(ROOT)}")

    # Append deduped wikilink bullets to journal
    journal_text = read_text(jp)
    from_kai_marker = "## 💬 From Kai"
    if from_kai_marker not in journal_text:
        raise ValueError(f"Section '{from_kai_marker}' not found in journal")

    links_to_add: List[str] = []
    if codex_transcript and codex_link not in journal_text:
        links_to_add.append(f"- {codex_link}：Life Copilot / planning / reflection conversations.")
    if renderer_transcript and renderer_link not in journal_text:
        links_to_add.append(f"- {renderer_link}：Obsidian-rendered Claude Code conversations.")

    if links_to_add:
        addition = "\n".join(links_to_add)
        write_text(jp, append_journal_section(journal_text, from_kai_marker, addition))
        print(f"  updated: {jp.relative_to(ROOT)}")
    else:
        print(f"  (wikilinks already present in {jp.relative_to(ROOT)})")

    print(str(jp))


# --- Memory commands ---

def ensure_memory_sections(text: str) -> str:
    required = ["## Stable Profile", "## Active Hypotheses (Last 30 Days)", "## Canonical Memories"]
    if all(s in text for s in required):
        return text

    appends = []
    if "## Memory Governance" not in text:
        appends.append("## Memory Governance (v2)\n- Stable Profile: low-frequency, identity-level stable traits.\n- Active Hypotheses: last 30 days, high relevance, fast-changing.\n- Canonical Memories: verified durable conclusions with evidence links.\n")

    templates = {
        "## Stable Profile": "## Stable Profile\n- (add stable traits here)\n",
        "## Active Hypotheses (Last 30 Days)": "## Active Hypotheses (Last 30 Days)\n- (new memory entries are appended here by script)\n",
        "## Canonical Memories": "## Canonical Memories\n- (promote only verified high-confidence patterns here)\n"
    }

    for s in required:
        if s not in text:
            appends.append(templates[s])

    if appends:
        text = text.rstrip() + "\n\n" + "\n".join(appends).rstrip()

    return text + "\n"


def insert_line_under_section(text: str, section: str, line: str) -> str:
    if line in text:
        return text
    pattern = re.compile(rf"(^## {re.escape(section)}\s*$)", re.MULTILINE)
    m = pattern.search(text)
    if not m:
        return text + f"\n## {section}\n- {line}\n"
    start = m.end()
    next_h = re.search(r"(?m)^## ", text[start:])
    end = start + next_h.start() if next_h else len(text)
    body = text[start:end].rstrip()
    body = (body + f"\n- {line}\n\n") if body else f"\n- {line}\n\n"
    return text[:start] + body + text[end:]


def cmd_writeback_memory(args: argparse.Namespace) -> None:
    if not MEMORY_FILE.exists():
        raise FileNotFoundError(f"Memory file not found: {MEMORY_FILE}")
    mem = ensure_memory_sections(read_text(MEMORY_FILE))
    entry = f"[{args.date}] {args.kind}: {args.content.strip()}"
    section = args.section or "Active Hypotheses (Last 30 Days)"
    write_text(MEMORY_FILE, insert_line_under_section(mem, section, entry))
    print(str(MEMORY_FILE))


def cmd_append_insight(args: argparse.Namespace) -> None:
    INSIGHTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not INSIGHTS_FILE.exists():
        schema = json.dumps({"_schema": "insight", "_version": "1.0", "_description": "Append-only log of cognitive insights."}, ensure_ascii=False)
        write_text(INSIGHTS_FILE, schema + "\n")
    existing = INSIGHTS_FILE.read_text().strip().splitlines()
    idx = len(existing)
    refs = re.findall(r"\[\[(\d{4}-\d{2}-\d{2})\]\]", args.content)
    name_m = re.search(r"\(([A-Z][A-Za-z\s\-]+)\)", args.content)
    record = {
        "id": f"insight_{args.date}_{idx:03d}", "date": args.date, "type": args.kind,
        "name": name_m.group(1).strip() if name_m else "",
        "content": args.content.strip(), "refs": refs, "status": "active",
    }
    with open(INSIGHTS_FILE, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(str(INSIGHTS_FILE))


def cmd_export_codex_thread(args: argparse.Namespace) -> None:
    if args.session_file:
        session_file = Path(args.session_file).expanduser()
    else:
        thread_id = args.thread_id or latest_codex_thread_id()
        session_file = codex_session_file_for_thread(thread_id)
    if not session_file.exists():
        raise FileNotFoundError(f"Codex session file not found: {session_file}")

    transcript = export_codex_transcript(
        session_file,
        assistant_name=args.assistant_name,
        user_name=args.user_name,
        include_commentary=args.include_commentary,
        keep_memory_citation=args.keep_memory_citation,
    )
    if not transcript.strip():
        raise ValueError(f"No user/assistant transcript messages found in {session_file}")

    if args.output_file:
        out_path = Path(args.output_file).expanduser()
    else:
        out_dir = Path(args.output_dir).expanduser() if args.output_dir else Path("/tmp")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = out_dir / f"from-codex-{stamp}.md"
    write_text(out_path, transcript)
    print(str(out_path))


def cmd_export_codex_day(args: argparse.Namespace) -> None:
    target = parse_date_str(args.date)
    transcript = export_codex_day_transcript(
        target,
        assistant_name=args.assistant_name,
        user_name=args.user_name,
        include_commentary=args.include_commentary,
        keep_memory_citation=args.keep_memory_citation,
    )
    if not transcript.strip():
        raise ValueError(f"No Codex transcript messages found for date: {target.isoformat()}")

    if args.output_file:
        out_path = Path(args.output_file).expanduser()
    else:
        out_dir = Path(args.output_dir).expanduser() if args.output_dir else Path("/tmp")
        out_path = out_dir / f"from-codex-{target.isoformat()}.md"
    write_text(out_path, transcript)
    print(str(out_path))


def cmd_compact_memory(_args: argparse.Namespace) -> None:
    """Move expired Active Hypotheses from memory.md to memory-archive.md."""
    if not MEMORY_FILE.exists():
        raise FileNotFoundError(f"Memory file not found: {MEMORY_FILE}")
    text = ensure_memory_sections(read_text(MEMORY_FILE))
    sections = split_markdown_sections(text)
    cutoff = date.today() - timedelta(days=MEMORY_RETENTION_DAYS)
    new_sections: List[Tuple[str, str]] = []
    to_archive: List[str] = []

    for heading, body in sections:
        if heading == "Active Hypotheses (Last 30 Days)":
            active: List[str] = []
            current_entry: List[str] = []
            is_expired = False
            
            for line in body.splitlines():
                if re.match(r"^[-*]\s*\[\d{4}-\d{2}-\d{2}\]", line.strip()):
                    if current_entry:
                        if is_expired:
                            to_archive.extend(current_entry)
                        else:
                            active.extend(current_entry)
                    current_entry = [line]
                    m = DATE_RE.search(line)
                    if m:
                        try:
                            is_expired = date.fromisoformat(m.group(1)) < cutoff
                        except ValueError:
                            is_expired = False
                    else:
                        is_expired = False
                else:
                    if current_entry:
                        current_entry.append(line)
                    else:
                        active.append(line)

            if current_entry:
                if is_expired:
                    to_archive.extend(current_entry)
                else:
                    active.extend(current_entry)

            new_sections.append((heading, "\n".join(active).strip()))
        elif heading == "Legacy Stream (Pre-v2)":
            # Legacy Stream no longer lives in hot memory; archive it first
            for line in body.splitlines():
                if line.strip():
                    to_archive.append(line)
            continue
        elif heading == "Compressed History":
            # Discard Compressed History completely
            continue
        else:
            new_sections.append((heading, body))

    # Write back hot memory (without Legacy Stream)
    out_lines: List[str] = []
    for h, b in new_sections:
        if h == "":
            if b:
                out_lines += [b, ""]
        else:
            out_lines += [f"## {h}", b, ""]

    # Dedup
    final: List[str] = []
    seen: set = set()
    for ln in "\n".join(out_lines).splitlines():
        key = ln.strip()
        if (key.startswith("- [") or key.startswith("* [")) and key in seen:
            continue
        seen.add(key)
        final.append(ln)

    write_text(MEMORY_FILE, "\n".join(final).rstrip() + "\n")

    # Append expired entries to cold archive
    if to_archive:
        archive_text = read_text(MEMORY_ARCHIVE_FILE) if MEMORY_ARCHIVE_FILE.exists() else ""
        archive_text = archive_text.rstrip() + "\n" + "\n".join(to_archive) + "\n"
        write_text(MEMORY_ARCHIVE_FILE, archive_text)

    print(f"compact done, archived {len(to_archive)} entries to memory-archive.md")


def cmd_sync_roadmap_stats(_args: argparse.Namespace) -> None:
    text = read_text(ROADMAP_FILE)
    lines = text.splitlines()
    checked = unchecked = 0
    current_h2 = current_h3 = first_h2 = first_h3 = ""

    for line in lines:
        stripped = line.strip()
        if line.startswith("## "):
            current_h2, current_h3 = line, ""
        elif line.startswith("### "):
            current_h3 = line
        if re.match(r"- \[[xX]\]", stripped):
            checked += 1
        elif re.match(r"- \[ \]", stripped):
            unchecked += 1
            if not first_h2:
                first_h2, first_h3 = current_h2, current_h3

    total = checked + unchecked
    pct = round(checked / total * 100) if total else 0
    lv_m = re.search(r"(Level \d+)", first_h2) if first_h2 else None
    emoji_map = {"Level 1": "🟢", "Level 2": "🟡", "Level 3": "🔴"}
    if lv_m:
        lv = lv_m.group(1)
        emoji = emoji_map.get(lv, "🟡")
        branch_m = re.search(r"Branch \w+[:\s]+([^\[#]+)", first_h3)
        phase_m = re.search(r"(Phase \d+[^(#\[]*)", first_h3)
        detail = (branch_m or phase_m).group(1).strip()[:45] if (branch_m or phase_m) else "in progress"
        status = f"{emoji} {lv} — {detail}"
    else:
        status = "🏁 All XPs Complete"

    new_lines = []
    for line in lines:
        if re.search(r"\*\*Total Readiness\*\*", line):
            line = re.sub(r"`\d+%`", f"`{pct}%`", line)
        elif re.search(r"\*\*Current Status\*\*", line):
            line = re.sub(r":.*$", f": {status}", line)
        new_lines.append(line)

    write_text(ROADMAP_FILE, "\n".join(new_lines) + "\n")
    print(f"Readiness: {pct}% ({checked}/{total} XPs) | Status: {status}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Life Copilot orchestration (lean)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sync-quant-state")
    s.add_argument("--date", required=True, help="Journal date to inspect for filled Legacy Quant Feedback (old heading 'Quant Protocol Feedback' also accepted).")
    s.add_argument("--chat-note", default="", help="Explicit manual override note. Allows sync even without filled journal feedback.")
    s.add_argument(
        "--allow-missing-journal",
        action="store_true",
        help="Permit a missing journal only when --chat-note is also provided; blank journal templates do not count as filled feedback.",
    )
    s.set_defaults(func=cmd_sync_quant_state)

    s = sub.add_parser("update-schedule")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--date",
        help="Base journal date. Refreshes the next day's schedule only when that journal has filled Legacy Quant Feedback (old heading also accepted).",
    )
    g.add_argument(
        "--target-date",
        help="Explicit manual override: generate or repoint the schedule for this date without journal-feedback gating.",
    )
    s.set_defaults(func=cmd_update_schedule)

    s = sub.add_parser("quant-mission")
    s.add_argument("--xp", required=True)
    s.add_argument("--date", required=False)
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_quant_mission)

    s = sub.add_parser(
        "quant-question-link",
        help="First-pass candidate retrieval for question links; inspect files before deciding.",
        description="First-pass candidate retrieval for question links; inspect files before deciding.",
    )
    s.add_argument("--question", required=True, help="The learning question to search for.")
    s.add_argument("--xp", default="", help="XP ID to boost in scoring (e.g. XP-31). Does not restrict search.")
    s.add_argument("--top", type=int, default=8, help="Number of top candidates to show. Default: 8.")
    s.add_argument("--json", action="store_true", help="Emit structured JSON instead of human-readable bullets.")
    s.set_defaults(func=cmd_quant_question_link)

    s = sub.add_parser("writeback-thought")
    s.add_argument("--date", required=True)
    s.add_argument("--title", required=True)
    s.add_argument("--input-file", required=True)
    s.set_defaults(func=cmd_writeback_thought)

    s = sub.add_parser("writeback-daily-suggestion")
    s.add_argument("--source-date", required=True, help="Date of the diary analysis that generated the suggestion (YYYY-MM-DD). Target diary is source-date + 1 day.")
    s.add_argument("--input-file", required=True, help="Path to file containing the suggestion content.")
    s.add_argument("--force", action="store_true", help="Overwrite existing suggestion even if it has different or missing provenance.")
    s.set_defaults(func=cmd_writeback_daily_suggestion)

    s = sub.add_parser("writeback-journal")
    s.add_argument("--date", required=True)
    s.add_argument("--input-file", required=True)
    s.set_defaults(func=cmd_writeback_journal)

    s = sub.add_parser("writeback-codex-thread")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--thread-id", help="Codex thread id from ~/.codex/session_index.jsonl. Defaults to latest.")
    g.add_argument("--session-file", help="Direct path to a Codex rollout jsonl file.")
    s.add_argument("--date", required=True)
    s.add_argument("--heading", help="Markdown h3 heading under From Kai. Defaults to the thread id.")
    s.add_argument("--user-name", default="Henry")
    s.add_argument("--assistant-name", default="Codex")
    s.add_argument("--include-commentary", action="store_true", help="Include assistant progress/status updates.")
    s.add_argument("--keep-memory-citation", action="store_true", help="Keep oai memory citation blocks in assistant messages.")
    s.add_argument("--replace", action="store_true", help="Replace the existing From Kai section instead of appending.")
    s.set_defaults(func=cmd_writeback_codex_thread)

    s = sub.add_parser("writeback-codex-day")
    s.add_argument("--date", required=True)
    s.add_argument("--heading", help="Markdown h3 heading under From Kai. Defaults to the date.")
    s.add_argument("--user-name", default="Henry")
    s.add_argument("--assistant-name", default="Codex")
    s.add_argument("--include-commentary", action="store_true", help="Include assistant progress/status updates.")
    s.add_argument("--keep-memory-citation", action="store_true", help="Keep oai memory citation blocks in assistant messages.")
    s.add_argument("--replace", action="store_true", help="Replace the existing From Kai section instead of appending.")
    s.set_defaults(func=cmd_writeback_codex_day)

    s = sub.add_parser("preview-ai-day")
    s.add_argument("--date", required=True)
    s.set_defaults(func=cmd_preview_ai_day)

    s = sub.add_parser("writeback-ai-day")
    s.add_argument("--date", required=True)
    s.set_defaults(func=cmd_writeback_ai_day)

    s = sub.add_parser("writeback-memory")
    s.add_argument("--date", required=True)
    s.add_argument("--kind", required=True)
    s.add_argument("--content", required=True)
    s.add_argument("--section", default="Active Hypotheses (Last 30 Days)")
    s.set_defaults(func=cmd_writeback_memory)

    s = sub.add_parser("append-insight")
    s.add_argument("--date", required=True)
    s.add_argument("--kind", required=True)
    s.add_argument("--content", required=True)
    s.set_defaults(func=cmd_append_insight)

    s = sub.add_parser("export-codex-thread")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--thread-id", help="Codex thread id from ~/.codex/session_index.jsonl. Defaults to latest.")
    g.add_argument("--session-file", help="Direct path to a Codex rollout jsonl file.")
    s.add_argument("--output-file", help="Write transcript to this markdown file.")
    s.add_argument("--output-dir", help="Directory for auto-named transcript output. Defaults to /tmp.")
    s.add_argument("--user-name", default="Henry")
    s.add_argument("--assistant-name", default="Codex")
    s.add_argument("--include-commentary", action="store_true", help="Include assistant progress/status updates.")
    s.add_argument("--keep-memory-citation", action="store_true", help="Keep oai memory citation blocks in assistant messages.")
    s.set_defaults(func=cmd_export_codex_thread)

    s = sub.add_parser("export-codex-day")
    s.add_argument("--date", required=True)
    s.add_argument("--output-file", help="Write combined transcript to this markdown file.")
    s.add_argument("--output-dir", help="Directory for auto-named transcript output. Defaults to /tmp.")
    s.add_argument("--user-name", default="Henry")
    s.add_argument("--assistant-name", default="Codex")
    s.add_argument("--include-commentary", action="store_true", help="Include assistant progress/status updates.")
    s.add_argument("--keep-memory-citation", action="store_true", help="Keep oai memory citation blocks in assistant messages.")
    s.set_defaults(func=cmd_export_codex_day)

    s = sub.add_parser("compact-memory")
    s.set_defaults(func=cmd_compact_memory)

    s = sub.add_parser("sync-roadmap-stats")
    s.set_defaults(func=cmd_sync_roadmap_stats)

    return p


def main() -> int:
    args = build_parser().parse_args()
    try:
        args.func(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
