#!/usr/bin/env python3
"""Close an explicitly requested bedtime turn without delaying the reply."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from copilot import is_bedtime_close_prompt  # noqa: E402


def marker_path(session_id: str, turn_id: str) -> Path:
    key = hashlib.sha256(f"{session_id}:{turn_id}".encode("utf-8")).hexdigest()
    return Path(tempfile.gettempdir()) / "life-copilot-bedtime" / f"{key}.json"


def read_payload() -> dict:
    try:
        value = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def user_prompt_submit(payload: dict) -> None:
    prompt = str(payload.get("prompt") or "")
    if not is_bedtime_close_prompt(prompt):
        print("{}")
        return
    session_id = str(payload.get("session_id") or "")
    turn_id = str(payload.get("turn_id") or "")
    if not session_id or not turn_id:
        print("{}")
        return
    marker = marker_path(session_id, turn_id)
    marker.parent.mkdir(parents=True, exist_ok=True)
    record = dict(payload)
    record["date"] = datetime.now().astimezone().date().isoformat()
    record["timestamp"] = datetime.now().astimezone().isoformat()
    marker.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": (
                "这是 Life Copilot v4.4 的晚安闭合请求。回答前先完成两项收尾："
                "若当日 trace 中有尚未进入正文的 Henry 经历、想法或澄清，"
                "合并后用 writeback-chat-capture 幂等刷新当日唯一自动补记；"
                "再运行 audit-system-rules，只在满足证据与硬评测时处理至多一个候选。"
                "最后的用户可见回复必须恰好一句有趣且出乎意料的晚安，不能附带执行报告。"
            ),
        }
    }, ensure_ascii=False))


def stop(payload: dict) -> None:
    session_id = str(payload.get("session_id") or "")
    turn_id = str(payload.get("turn_id") or "")
    marker = marker_path(session_id, turn_id)
    if not marker.exists():
        print("{}")
        return
    try:
        original = json.loads(marker.read_text(encoding="utf-8"))
        merged = {**original, **payload}
        merged["prompt"] = original.get("prompt", "")
        merged["date"] = (
            original.get("date")
            or datetime.now().astimezone().date().isoformat()
        )
        hook_input = marker.with_name(marker.stem + "-stop.json")
        hook_input.write_text(
            json.dumps(merged, ensure_ascii=False),
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "copilot.py"),
                "finalize-ai-day",
                "--hook-input-file",
                str(hook_input),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=25,
            check=False,
        )
        if result.returncode == 0:
            marker.unlink(missing_ok=True)
            hook_input.unlink(missing_ok=True)
        else:
            detail = (result.stderr or result.stdout).strip()
            print(
                f"Life Copilot bedtime finalizer failed: {detail}",
                file=sys.stderr,
            )
    except Exception as exc:
        print(f"Life Copilot bedtime finalizer failed: {exc}", file=sys.stderr)
    # Stop requires JSON on stdout. Archival failure must never swallow bedtime.
    print("{}")


def main() -> None:
    payload = read_payload()
    event = payload.get("hook_event_name")
    if event == "UserPromptSubmit":
        user_prompt_submit(payload)
    elif event == "Stop":
        stop(payload)
    else:
        print("{}")


if __name__ == "__main__":
    main()
