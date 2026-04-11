#!/usr/bin/env python3
"""
Life Copilot — lean orchestration utilities.

Only structural write commands that are unsafe for Claude to do freehand:
writeback-journal, writeback-thought, writeback-memory, append-insight,
compact-memory, quant-mission, sync-quant-state,
sync-roadmap-stats, update-schedule.
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

MEMORY_RETENTION_DAYS = 30

DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
JOURNAL_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
XP_OPEN_RE = re.compile(r"^- \[ \] \*\*(XP-[^*]+)\*\*: (.+)$")
XP_DONE_RE = re.compile(r"^- \[x\] \*\*(XP-[^*]+)\*\*: (.+)$", re.IGNORECASE)
XP_TAG_RE = re.compile(r"#(course|lab)\b", re.IGNORECASE)


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
        if line.strip().startswith("## 📊 Quant Protocol Feedback"):
            start = i
        elif start is not None and i > start and line.strip().startswith("## "):
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
        "morning_score": find(r"Morning Block:\s*`?([^`\n]+)`?"),
        "afternoon_score": find(r"Afternoon Block:\s*`?([^`\n]+)`?"),
        "evening_score": find(r"Evening Block:\s*`?([^`\n]+)`?"),
        "roadblocks": find(r"\*{0,2}Roadblocks\*{0,2}:\s*([^\n]+)"),
        "energy": find(r"\*{0,2}Energy Level \(AM/PM/Eve\)\*{0,2}:\s*`?([^`\n]+)`?"),
        "tomorrow_request": find(r"\*{0,2}Request for Tomorrow\*{0,2}:\s*([^\n]+)"),
    }


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
    focus = ", ".join(focus_items) if focus_items else "maintain momentum"

    journal_path = journal_path_for_date(today)
    if journal_path.exists():
        fb = extract_quant_feedback(read_text(journal_path))
        if fb.get("tomorrow_request"):
            hints.insert(0, f"tomorrow_request={fb['tomorrow_request']}")
        if fb.get("roadblocks"):
            hints.insert(0, f"roadblocks={fb['roadblocks']}")
        scores = ", ".join(x for x in [fb.get("morning_score"), fb.get("afternoon_score"), fb.get("evening_score")] if x)
        evidence.insert(0, f"[{today}] journal={journal_path.relative_to(ROOT)} scores={scores or 'n/a'}")
    elif args.allow_missing_journal:
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

    roadmap_content = read_text(ROADMAP_FILE)
    schedule_path = _schedule_file_path(target)

    # Overwrite guard: only skip when the exact target schedule already exists.
    # If the file exists but roadmap points elsewhere, just repoint the pointer.
    if schedule_path.exists():
        if _extract_schedule_date(roadmap_content) != target:
            write_text(ROADMAP_FILE, _update_roadmap_pointer(roadmap_content, target))
        print(str(schedule_path))
        return

    schedule_path.parent.mkdir(parents=True, exist_ok=True)
    write_text(schedule_path, build_active_schedule_block(base))
    write_text(ROADMAP_FILE, _update_roadmap_pointer(roadmap_content, target))
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
    m2 = re.search(r"## ⚡️ Active Schedule:.*?(\w+), (\w+) (\d+), (\d{4})", content)
    if m2:
        try:
            return datetime.strptime(f"{m2.group(2)} {m2.group(3)} {m2.group(4)}", "%b %d %Y").date()
        except ValueError:
            pass
    return None


def build_active_schedule_block(base_date: date) -> str:
    target = base_date + timedelta(days=1)
    state = load_quant_state()
    pending = [p for p in state.get("pending_xp", []) if isinstance(p, str) and p and p != "(none)"]
    top = pending[:4] if pending else ["XP-15: Array Mediums", "XP-16: DP Basics", "XP-17: HashMap"]
    focus = state.get("current_focus", "quant execution")
    hints = [h for h in state.get("schedule_hints", []) if isinstance(h, str)]

    fb = extract_quant_feedback(read_text(journal_path_for_date(base_date))) if journal_path_for_date(base_date).exists() else {}
    tr = fb.get("tomorrow_request") or next((h.split("=", 1)[1] for h in hints if h.startswith("tomorrow_request=")), "")
    rb = fb.get("roadblocks") or next((h.split("=", 1)[1] for h in hints if h.startswith("roadblocks=")), "")
    weekday = target.strftime("%A")
    date_label = target.strftime("%b %-d, %Y") if os.name != "nt" else target.strftime("%b %#d, %Y")
    xp_targets = focus
    xp_morning = top[0]
    xp_afternoon = top[1] if len(top) > 1 else top[0]
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

    b = [
        f"## ⚡️ Active Schedule: {format_day_label(target)}",
        f"*Focus: {focus}*", "",
        "> **Current Protocol**: **[FULL POWER]** High-intensity deep work.",
        f"> **Target**: {', '.join(t.split(':')[0] for t in top[:3])}.",
        f"> **Context Hint**: Yesterday's request: {tr if tr else '(none)'}; Roadblocks: {rb if rb else '(none)'}.", "",
        "| Time | Block Name | Target Task |",
        "| :--- | :--------- | :---------- |",
        "| **07:30 - 08:30** | **🌅 Morning Routine** | Wake, hygiene, ride to library. |",
        f"| **08:30 - 12:00** | **⚔️ Deep Work A** | {xp_morning}. |",
        "| **12:00 - 13:00** | **🍲 Lunch** | Fixed Time Anchor. |",
        "| **13:00 - 14:00** | **💤 Power Nap** | Non-negotiable Recovery. |",
        f"| **14:00 - 17:00** | **⚔️ Deep Work B** | {xp_afternoon}. |",
        "| **17:00 - 18:00** | **🍲 Dinner** | Fixed Time Anchor. |",
        "| **18:00 - 22:00** | **🕹️ Agency Time** | Free-choice block: sports / reading / social / casual exploration. No execution score applied. |",
        "| **22:00 - 22:30** | **📔 Reflection** | Daily log + quant feedback. |",
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

def append_thought_to_journal(journal_text: str, title: str, content: str) -> str:
    # Guardrail: this command is for writing user-side diary thoughts,
    # not for writing Copilot analysis into the journal body.
    analysis_markers = [
        "## What Life Copilot Said",
        "## 🌡️ 情绪与能量状态",
        "## 🧠 深度洞察",
        "## 🧭 Copilot 建议",
        "## ❓ 深度追问",
        "## 💾 记忆更新",
        "## 📊 进展追踪",
        "## 🔇 沉默议题提醒",
    ]
    if any(marker in content for marker in analysis_markers):
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
    daily_bullet = f"- [ ] {title}\n"

    tr_start, tr_end = section_bounds("Thoughts & Reflections")
    if tr_start is None:
        raise ValueError("Section '💭 Thoughts & Reflections' not found in journal")
    i = tr_end - 1
    while i > tr_start and lines[i].strip() == "":
        i -= 1
    lines.insert(i + 1, thought_block)

    dl_start, dl_end = section_bounds("Daily Log")
    if dl_start is None:
        raise ValueError("Section '📝 Daily Log' not found in journal")
    j = dl_end - 1
    while j > dl_start and lines[j].strip() == "":
        j -= 1
    lines.insert(j + 1, daily_bullet)
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


def cmd_writeback_journal(args: argparse.Namespace) -> None:
    target = parse_date_str(args.date)
    jp = journal_path_for_date(target)
    if not jp.exists():
        raise FileNotFoundError(f"Journal not found: {jp}")
    if not args.input_file:
        raise ValueError("--input-file is required")
    write_text(jp, replace_journal_copilot_section(read_text(jp), read_text(Path(args.input_file))))
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
    s.add_argument("--date", required=True)
    s.add_argument("--chat-note", default="")
    s.add_argument("--allow-missing-journal", action="store_true")
    s.set_defaults(func=cmd_sync_quant_state)

    s = sub.add_parser("update-schedule")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--date", help="Base date. Generates the next day's schedule.")
    g.add_argument("--target-date", help="Explicit schedule date to generate or repoint to.")
    s.set_defaults(func=cmd_update_schedule)

    s = sub.add_parser("quant-mission")
    s.add_argument("--xp", required=True)
    s.add_argument("--date", required=False)
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_quant_mission)

    s = sub.add_parser("writeback-thought")
    s.add_argument("--date", required=True)
    s.add_argument("--title", required=True)
    s.add_argument("--input-file", required=True)
    s.set_defaults(func=cmd_writeback_thought)

    s = sub.add_parser("writeback-journal")
    s.add_argument("--date", required=True)
    s.add_argument("--input-file", required=True)
    s.set_defaults(func=cmd_writeback_journal)

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
