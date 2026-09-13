#!/usr/bin/env python3
"""Local semantic recall over the Life journal: diaries and AI conversation traces.

Usage:
  python3 tools/recall/recall.py index [--full]
  python3 tools/recall/recall.py search "query" ["another query" ...] [-k 10] [--before YYYY-MM-DD]
                                        [--kinds handwritten,transcribed,copilot,trace] [--json] [--no-update]
  python3 tools/recall/recall.py status

Search updates the index for new or changed files first, so there is no background job.
Results are candidates only: open the original file at the listed lines before citing it.
"""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np

TOOL_DIR = Path(__file__).resolve().parent
ROOT = TOOL_DIR.parents[1]
DATA_DIR = TOOL_DIR / "data"
CHUNKS_FILE = DATA_DIR / "chunks.jsonl"
EMB_FILE = DATA_DIR / "embeddings.npy"
MANIFEST_FILE = DATA_DIR / "manifest.json"
LOCK_FILE = DATA_DIR / ".lock"

MODEL_ID = "microsoft/harrier-oss-v1-0.6b"
CHUNKING_VERSION = "sentences-200t-50overlap-v1"
TARGET_TOKENS = 200
OVERLAP_TOKENS = 50
MAX_SEQ_TOKENS = 512
QUERY_TASK = "Given a question about something that happened in the author's life, retrieve diary or conversation passages that describe it"
LITERAL_BOOST = 0.1

DIARY_RE = re.compile(r"^journal/\d{4}/\d{2}/\d{4}-\d{2}-\d{2}\.md$")
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
TRANSCRIPT_RE = re.compile(r"^>\s*\[!info\]\s*对话转写")
SENTENCE_RE = re.compile(r"(?<=[。！？!?])|(?<=[.;；])\s+")
COPILOT_KEYS = ("Copilot", "copilot", "Suggestion", "建议", "洞察", "Insight", "分析", "Analysis", "记忆更新", "进展追踪", "情绪与能量")
HANDWRITTEN_KEYS = ("Thoughts", "Reflection", "Moment", "Writing State", "Tomorrow Projection", "Habits", "Daily Log", "想法", "反思")
SKIP_KEYS = ("From Kai",)
KIND_LABELS = {"handwritten": "手写", "transcribed": "转写", "copilot": "分析", "trace": "对话记录", "other": "其他"}


# ---------- sources and chunking ----------

def list_sources():
    files = []
    for dirpath, dirnames, filenames in os.walk(ROOT / "journal"):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if not name.endswith(".md"):
                continue
            rel = (Path(dirpath) / name).relative_to(ROOT).as_posix()
            if DIARY_RE.match(rel) or rel.startswith("journal/ai-conversations/"):
                files.append(rel)
    return sorted(files)


def section_kind(heading):
    if any(k in heading for k in SKIP_KEYS):
        return "skip"
    if any(k in heading for k in COPILOT_KEYS):
        return "copilot"
    if any(k in heading for k in HANDWRITTEN_KEYS):
        return "handwritten"
    return "other"


def labeled_lines(rel, text):
    """Yield (line_no, kind, section, text) for lines worth indexing, with provenance labels."""
    lines = text.splitlines()
    is_trace = rel.startswith("journal/ai-conversations/")
    kind = "trace" if is_trace else "handwritten"
    section = ""
    transcript = None  # None, "plain" or "capture"
    blank_run = 0
    in_fence = False
    start = 0
    if lines and lines[0].strip() == "---":
        for j in range(1, len(lines)):
            if lines[j].strip() == "---":
                start = j + 1
                break
    for i in range(start, len(lines)):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not stripped:
            blank_run += 1
            if transcript == "plain" and blank_run >= 2:
                transcript = None
            continue
        blank_run = 0
        heading = HEADING_RE.match(stripped)
        if heading:
            level, title = len(heading.group(1)), heading.group(2).strip()
            if transcript == "plain" or (transcript == "capture" and level <= 2):
                transcript = None
            if not is_trace and level == 2:
                kind = section_kind(title)
                section = title
            elif is_trace and level <= 3:
                section = title
            continue
        if TRANSCRIPT_RE.match(stripped):
            window = " ".join(lines[i + 1:i + 4])
            transcript = "capture" if "capture-id:" in window else "plain"
            continue
        if stripped.startswith(">") and (transcript or "Generated from [[" in stripped):
            continue
        if stripped.startswith("#diary") or re.fullmatch(r"[-*]?\s*(\[\[[^\]]+\]\][：:，,\s\w-]*)+", stripped):
            continue
        effective = "transcribed" if transcript else kind
        if effective == "skip":
            continue
        content = stripped.lstrip("> ").strip()
        if content:
            yield i + 1, effective, section, content


def sentences_for(line):
    parts = [p.strip() for p in SENTENCE_RE.split(line)]
    return [p for p in parts if p]


def chunk_file(rel, text, tokenizer):
    rows = []
    date_match = DATE_RE.search(Path(rel).name)
    date = date_match.group(1) if date_match else ""
    segments = []  # consecutive lines sharing kind and section
    for line_no, kind, section, content in labeled_lines(rel, text):
        if segments and segments[-1]["kind"] == kind and segments[-1]["section"] == section:
            segments[-1]["lines"].append((line_no, content))
        else:
            segments.append({"kind": kind, "section": section, "lines": [(line_no, content)]})
    for seg in segments:
        sents = [(s, line_no) for line_no, content in seg["lines"] for s in sentences_for(content)]
        if not sents:
            continue
        encoded = tokenizer([s for s, _ in sents], add_special_tokens=False, return_offsets_mapping=True)
        units = []
        for (s, line_no), ids, offsets in zip(sents, encoded["input_ids"], encoded["offset_mapping"]):
            if len(ids) <= TARGET_TOKENS:
                units.append((s, line_no, len(ids)))
                continue
            for a in range(0, len(ids), TARGET_TOKENS):
                piece = offsets[a:a + TARGET_TOKENS]
                units.append((s[piece[0][0]:piece[-1][1]], line_no, len(piece)))
        current, tokens, fresh = [], 0, 0
        for unit in units:
            if current and tokens + unit[2] > TARGET_TOKENS:
                if fresh:
                    rows.append(_make_row(rel, date, seg, current))
                carry, carried = [], 0
                for u in reversed(current):
                    if carried + u[2] > OVERLAP_TOKENS:
                        break
                    carry.insert(0, u)
                    carried += u[2]
                current, tokens, fresh = carry, carried, 0
            current.append(unit)
            tokens += unit[2]
            fresh += 1
        if current and fresh:
            rows.append(_make_row(rel, date, seg, current))
    return rows


def _make_row(rel, date, seg, units):
    text = " ".join(u[0] for u in units)
    return {"path": rel, "date": date, "kind": seg["kind"], "section": seg["section"],
            "line_start": min(u[1] for u in units), "line_end": max(u[1] for u in units), "text": text}


# ---------- model and storage ----------

_MODEL = None


def load_model():
    global _MODEL
    if _MODEL is None:
        import torch
        from sentence_transformers import SentenceTransformer
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        _MODEL = SentenceTransformer(MODEL_ID, device=device, model_kwargs={"dtype": "auto"})
        _MODEL.max_seq_length = MAX_SEQ_TOKENS
    return _MODEL


def load_index():
    if not (CHUNKS_FILE.exists() and EMB_FILE.exists() and MANIFEST_FILE.exists()):
        return [], None, {}
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    if manifest.get("model") != MODEL_ID or manifest.get("chunking") != CHUNKING_VERSION:
        return [], None, {}
    with CHUNKS_FILE.open(encoding="utf-8") as f:
        chunks = [json.loads(line) for line in f if line.strip()]
    emb = np.load(EMB_FILE)
    if len(chunks) != len(emb):
        return [], None, {}
    return chunks, emb, manifest


def save_index(chunks, emb, files):
    DATA_DIR.mkdir(exist_ok=True)
    tmp_chunks, tmp_emb, tmp_manifest = CHUNKS_FILE.with_suffix(".tmp"), DATA_DIR / "embeddings.tmp.npy", MANIFEST_FILE.with_suffix(".tmp")
    with tmp_chunks.open("w", encoding="utf-8") as f:
        for row in chunks:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    np.save(tmp_emb, emb.astype(np.float16))
    tmp_manifest.write_text(json.dumps({
        "model": MODEL_ID, "chunking": CHUNKING_VERSION,
        "updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "files": files,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp_chunks.replace(CHUNKS_FILE)
    tmp_emb.replace(EMB_FILE)
    tmp_manifest.replace(MANIFEST_FILE)


def update_index(full=False, verbose=True):
    DATA_DIR.mkdir(exist_ok=True)
    with LOCK_FILE.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        chunks, emb, manifest = ([], None, {}) if full else load_index()
        old_files = manifest.get("files", {}) if manifest else {}
        current = list_sources()
        changed, files = [], {}
        for rel in current:
            st = (ROOT / rel).stat()
            old = old_files.get(rel)
            if old and old["mtime"] == st.st_mtime and old["size"] == st.st_size:
                files[rel] = old
                continue
            data = (ROOT / rel).read_bytes()
            digest = hashlib.sha1(data).hexdigest()
            if old and old["sha1"] == digest:
                files[rel] = {**old, "mtime": st.st_mtime, "size": st.st_size}
                continue
            files[rel] = {"mtime": st.st_mtime, "size": st.st_size, "sha1": digest}
            changed.append(rel)
        removed = set(old_files) - set(current)
        if not changed and not removed and emb is not None:
            if files != old_files:
                save_index(chunks, emb, files)
            return 0, 0
        drop = set(changed) | removed
        keep = [i for i, row in enumerate(chunks) if row["path"] not in drop]
        kept_chunks = [chunks[i] for i in keep]
        kept_emb = emb[keep] if emb is not None and keep else np.zeros((0, 0), dtype=np.float16)
        model = load_model()
        new_rows = []
        for rel in changed:
            text = (ROOT / rel).read_text(encoding="utf-8", errors="ignore")
            new_rows.extend(chunk_file(rel, text, model.tokenizer))
        t0 = time.time()
        if new_rows:
            if verbose:
                print(f"embedding {len(new_rows)} chunks from {len(changed)} files...", file=sys.stderr)
            new_emb = model.encode([r["text"] for r in new_rows], batch_size=32, normalize_embeddings=True,
                                   convert_to_numpy=True, show_progress_bar=verbose and len(new_rows) > 500)
        else:
            new_emb = np.zeros((0, model.get_sentence_embedding_dimension()), dtype=np.float32)
        all_emb = new_emb.astype(np.float16) if kept_emb.size == 0 else np.vstack([kept_emb, new_emb.astype(np.float16)])
        save_index(kept_chunks + new_rows, all_emb, files)
        if verbose:
            print(f"index: +{len(new_rows)} chunks from {len(changed)} changed files, "
                  f"{len(removed)} removed files, {len(kept_chunks) + len(new_rows)} total ({time.time() - t0:.1f}s)",
                  file=sys.stderr)
        return len(changed), len(new_rows)


# ---------- search ----------

def encode_queries(model, queries):
    prompt = f"Instruct: {QUERY_TASK}\nQuery: "
    return model.encode([prompt + q for q in queries], normalize_embeddings=True, convert_to_numpy=True)


def merge_hits(order, scores, chunks, k):
    merged = []
    for idx in order:
        row = chunks[idx]
        for hit in merged:
            if hit["path"] == row["path"] and row["line_start"] <= hit["line_end"] + 1 and row["line_end"] >= hit["line_start"] - 1:
                hit["line_start"] = min(hit["line_start"], row["line_start"])
                hit["line_end"] = max(hit["line_end"], row["line_end"])
                break
        else:
            merged.append({**row, "score": float(scores[idx])})
            if len(merged) >= k:
                break
    return merged


def search(queries, k=10, before=None, kinds=None, no_update=False):
    if not no_update:
        update_index(verbose=True)
    chunks, emb, _ = load_index()
    if emb is None or not chunks:
        raise SystemExit("index is empty; run: python3 tools/recall/recall.py index")
    model = load_model()
    q = encode_queries(model, queries)
    matrix = emb.astype(np.float32)
    allowed = np.ones(len(chunks), dtype=bool)
    for i, row in enumerate(chunks):
        if before and (not row["date"] or row["date"] > before):
            allowed[i] = False
        if kinds and row["kind"] not in kinds:
            allowed[i] = False
    results = []
    for qi, query in enumerate(queries):
        scores = matrix @ q[qi]
        needle = query.strip().strip("\"“”「」").lower()
        if 0 < len(needle) <= 16:
            for i, row in enumerate(chunks):
                if needle in row["text"].lower():
                    scores[i] += LITERAL_BOOST
        scores = np.where(allowed, scores, -np.inf)
        order = np.argsort(-scores)[: k * 20]
        order = [i for i in order if np.isfinite(scores[i])]
        results.append({"query": query, "hits": merge_hits(order, scores, chunks, k)})
    return results


def print_results(results):
    for block in results:
        print(f"\n查询：{block['query']}")
        for rank, hit in enumerate(block["hits"], 1):
            snippet = re.sub(r"\s+", " ", hit["text"])[:90]
            where = f"{hit['path']}:{hit['line_start']}-{hit['line_end']}"
            print(f"{rank:>2}  {hit['score']:.3f}  {hit['date'] or '----------'}  {KIND_LABELS.get(hit['kind'], hit['kind']):<4}  {where}")
            print(f"    {snippet}")
    print("\n结果只是候选：引用前打开原文；命中「转写 / 分析 / 对话记录」时，按日期回到当天的原始日记。")


def main():
    parser = argparse.ArgumentParser(description="Local semantic recall over the Life journal.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_index = sub.add_parser("index", help="build or incrementally update the index")
    p_index.add_argument("--full", action="store_true", help="re-embed everything from scratch")
    p_search = sub.add_parser("search", help="search with one or more queries")
    p_search.add_argument("queries", nargs="+")
    p_search.add_argument("-k", type=int, default=10)
    p_search.add_argument("--before", help="only passages dated on or before YYYY-MM-DD")
    p_search.add_argument("--kinds", help="comma list: handwritten,transcribed,copilot,trace,other")
    p_search.add_argument("--json", action="store_true")
    p_search.add_argument("--no-update", action="store_true", help="skip the incremental update")
    sub.add_parser("status", help="show index size and freshness")
    args = parser.parse_args()

    if args.cmd == "index":
        update_index(full=args.full)
    elif args.cmd == "search":
        kinds = set(args.kinds.split(",")) if args.kinds else None
        results = search(args.queries, k=args.k, before=args.before, kinds=kinds, no_update=args.no_update)
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=1))
        else:
            print_results(results)
    else:
        chunks, emb, manifest = load_index()
        kinds = {}
        for row in chunks:
            kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
        print(json.dumps({"model": MODEL_ID, "updated": manifest.get("updated"), "files": len(manifest.get("files", {})),
                          "chunks": len(chunks), "by_kind": kinds}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
