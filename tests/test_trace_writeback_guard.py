"""Tests for non-destructive AI trace writeback."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import copilot

DAY = date(2026, 8, 13)
CODEX_THREAD = "### Codex Thread 11111111-1111-4111-8111-111111111111"
CODEX_ID = "11111111-1111-4111-8111-111111111111"


def _ts(hour: int, minute: int, second: int = 0) -> str:
    return datetime(2026, 8, 13, hour, minute, second).astimezone().isoformat()


def _msg(hour: int, minute: int, speaker: str, text: str) -> str:
    return f"[{copilot.format_chat_timestamp(_ts(hour, minute))}] {speaker}: {text}"


def _rec(session: str, hour: int, minute: int, role: str, text: str) -> copilot.SourceRecord:
    return (session, copilot.format_chat_timestamp(_ts(hour, minute)), role, copilot.trace_match_text(text))


def _join(*parts: str) -> str:
    return "\n\n".join(parts) + "\n"


def _trace_file(source: str, transcript: str) -> str:
    return "\n".join([
        "---",
        "date: 2026-08-13",
        f"source: {source}",
        "generated_by: scripts/copilot.py writeback-ai-day",
        "---",
        "",
        f"# 2026-08-13 {source} Trace",
        "",
        transcript,
    ])


def _no_records():
    raise AssertionError("source records must only be read when something is missing")


def _guard(source: str, old: str, new: str, records=_no_records):
    return copilot.guard_trace_transcript(
        _trace_file(source, old),
        new,
        source,
        records if callable(records) else (lambda: records),
    )


class TestTraceUnits(unittest.TestCase):
    def test_units_rebuild_the_body_and_ignore_look_alike_lines(self):
        body = _join(
            CODEX_THREAD,
            _msg(9, 0, "Henry", "问题"),
            _msg(9, 1, "Codex", "回答的第一段\n\n### 一句话总结\n[8/13/26 9:03 AM] Claude: 引用"),
        )
        units = copilot.split_trace_units(body, "Codex")
        self.assertEqual("\n".join(line for unit in units for line in unit["lines"]), body)
        self.assertEqual([unit["kind"] for unit in units], ["heading", "message", "message"])
        self.assertIn("Claude: 引用", units[-1]["text"])

    def test_manual_block_timestamps_with_narrow_space_are_messages(self):
        body = (
            "<!-- openclaw-manual-begin channel=telegram source=henry-paste -->\n"
            "### Kai / Telegram (supplied by Henry)\n\n"
            "[8/13/26 4:42 AM] Henry: 在吗\n"
            "[8/13/26 4:51 AM] Kai: 在。\n"
            "<!-- openclaw-manual-end -->\n"
        )
        units = copilot.split_trace_units(body, "Kai")
        messages = [unit for unit in units if unit["kind"] == "message"]
        self.assertEqual([unit["ts"] for unit in messages], ["8/13/26 4:42 AM", "8/13/26 4:51 AM"])
        self.assertTrue(all(unit["manual"] for unit in messages))


class TestTraceGuard(unittest.TestCase):
    def test_export_that_keeps_everything_is_written_unchanged(self):
        old = _join(CODEX_THREAD, _msg(9, 0, "Henry", "问题"))
        new = _join(CODEX_THREAD, _msg(9, 0, "Henry", "问题"), _msg(9, 1, "Codex", "回答"))
        self.assertEqual(_guard("codex", old, new), (new, [], []))

    def test_retries_the_rollout_dropped_are_merged_back_in_place(self):
        retries = [_msg(11, minute, "Henry", "这个功能有什么限制") for minute in (24, 25, 26, 27, 30)]
        old = _join(CODEX_THREAD, _msg(10, 0, "Henry", "开始"), *retries,
                    _msg(16, 34, "Henry", "这个功能有什么限制"), _msg(16, 35, "Codex", "主要有三点。"))
        new = _join(CODEX_THREAD, _msg(10, 0, "Henry", "开始"),
                    _msg(16, 34, "Henry", "这个功能有什么限制"), _msg(16, 35, "Codex", "主要有三点。"))
        records = [
            _rec(CODEX_ID, 10, 0, "user", "开始"),
            _rec(CODEX_ID, 16, 34, "user", "这个功能有什么限制"),
            _rec(CODEX_ID, 16, 35, "assistant", "主要有三点。"),
        ]
        merged, lost, dropped = _guard("codex", old, new, records)
        self.assertEqual(len(lost), 5)
        self.assertEqual(dropped, [])
        self.assertEqual(merged, old)

    def test_one_source_message_accounts_for_one_archived_copy(self):
        old = _join(CODEX_THREAD, _msg(10, 0, "Henry", "再试一次"), _msg(10, 0, "Henry", "再试一次"),
                    _msg(10, 1, "Codex", "好的"))
        new = _join(CODEX_THREAD, _msg(10, 0, "Henry", "再试一次"), _msg(10, 1, "Codex", "好的"))
        records = [_rec(CODEX_ID, 10, 0, "user", "再试一次"), _rec(CODEX_ID, 10, 1, "assistant", "好的")]
        merged, lost, _ = _guard("codex", old, new, records)
        self.assertEqual(len(lost), 1)
        self.assertEqual(merged, old)

    def test_edited_resend_does_not_stand_in_for_the_rolled_back_draft(self):
        draft = _msg(10, 0, "Henry", "请检查计划。")
        edited = _msg(10, 0, "Henry", "请检查计划。\n\n也看看预算。")
        old = _join(CODEX_THREAD, draft, edited, _msg(10, 1, "Codex", "已检查。"))
        new = _join(CODEX_THREAD, edited, _msg(10, 1, "Codex", "已检查。"))
        records = [
            _rec(CODEX_ID, 10, 0, "user", "请检查计划。\n\n也看看预算。"),
            _rec(CODEX_ID, 10, 1, "assistant", "已检查。"),
        ]
        merged, lost, _ = _guard("codex", old, new, records)
        self.assertEqual([unit["text"] for unit in lost], [draft])
        self.assertEqual(merged, old)

    def test_messages_the_importer_now_filters_or_rewrites_can_leave(self):
        injected = "<environment_context>\n  <cwd>/tmp/project</cwd>\n</environment_context>"
        old = _join(
            CODEX_THREAD,
            _msg(9, 0, "Henry", injected),
            _msg(9, 0, "Henry", "看这个"),
            # Its rollout record is gone, but the importer would drop it anyway.
            _msg(9, 5, "Henry", "<skill>\n<name>demo</name>\n</skill>"),
            _msg(9, 6, "Codex", "看到了。"),
        )
        new = _join(CODEX_THREAD, _msg(9, 0, "Henry", "[Image]\n\n看这个"), _msg(9, 6, "Codex", "看到了。"))
        records = [
            _rec(CODEX_ID, 9, 0, "user", injected),
            _rec(CODEX_ID, 9, 0, "user", "看这个"),
            _rec(CODEX_ID, 9, 6, "assistant", "看到了。"),
        ]
        merged, lost, dropped = _guard("codex", old, new, records)
        self.assertEqual(lost, [])
        self.assertEqual(len(dropped), 3)
        self.assertEqual(merged, new)

    def test_fork_copies_leave_while_the_fork_file_still_holds_them(self):
        shared = [_msg(10, 0, "Henry", "第一个问题"), _msg(10, 0, "Claude", "第一个回答")]
        old = _join("### Claude Code Session fork - 讨论", *shared, _msg(11, 5, "Henry", "改写后的问题"),
                    _msg(11, 5, "Claude", "改写后的回答"), "### Claude Code Session original - 讨论", *shared)
        new = _join("### Claude Code Session original - 讨论", *shared,
                    "### Claude Code Session fork - 讨论 (branched from original)",
                    _msg(11, 5, "Henry", "改写后的问题"), _msg(11, 5, "Claude", "改写后的回答"))
        records = [
            _rec(session, 10, 0, role, text)
            for session in ("original", "fork")
            for role, text in (("user", "第一个问题"), ("assistant", "第一个回答"))
        ] + [_rec("fork", 11, 5, "user", "改写后的问题"), _rec("fork", 11, 5, "assistant", "改写后的回答")]
        merged, lost, dropped = _guard("claude-code", old, new, records)
        self.assertEqual((lost, len(dropped)), ([], 2))
        self.assertEqual(merged, new)

    def test_lost_session_is_rebuilt_between_the_sessions_around_it(self):
        old = _join(
            "### Kai / Telegram Session morning", _msg(9, 0, "Henry", "早"), _msg(9, 1, "Kai", "早上好"),
            "### Kai / Telegram Session noon", _msg(12, 0, "Henry", "午饭吃什么"), _msg(12, 1, "Kai", "面"),
            "### Kai / Telegram Session evening", _msg(18, 0, "Henry", "晚上好"),
        )
        new = _join(
            "### Kai / Telegram Session morning", _msg(9, 0, "Henry", "早"), _msg(9, 1, "Kai", "早上好"),
            "### Kai / WeChat Session late-found", _msg(10, 0, "Henry", "新找到的会话"),
            "### Kai / Telegram Session evening", _msg(18, 0, "Henry", "晚上好"),
        )
        records = [
            _rec("morning", 9, 0, "user", "早"), _rec("morning", 9, 1, "assistant", "早上好"),
            _rec("late-found", 10, 0, "user", "新找到的会话"), _rec("evening", 18, 0, "user", "晚上好"),
        ]
        merged, lost, _ = _guard("openclaw", old, new, records)
        self.assertEqual(len(lost), 2)
        self.assertEqual(merged, _join(
            "### Kai / Telegram Session morning", _msg(9, 0, "Henry", "早"), _msg(9, 1, "Kai", "早上好"),
            "### Kai / WeChat Session late-found", _msg(10, 0, "Henry", "新找到的会话"),
            "### Kai / Telegram Session noon", _msg(12, 0, "Henry", "午饭吃什么"), _msg(12, 1, "Kai", "面"),
            "### Kai / Telegram Session evening", _msg(18, 0, "Henry", "晚上好"),
        ))

    def test_kept_message_goes_after_newly_archived_earlier_replies(self):
        old = _join("### Kai / Telegram Session s", _msg(9, 0, "Henry", "问一下"),
                    _msg(9, 2, "Kai", "旧的文字回复"), _msg(9, 10, "Henry", "谢谢"))
        new = _join("### Kai / Telegram Session s", _msg(9, 0, "Henry", "问一下"),
                    _msg(9, 1, "Kai", "通过消息工具发出的回复"), _msg(9, 10, "Henry", "谢谢"))
        records = [
            _rec("s", 9, 0, "user", "问一下"),
            _rec("s", 9, 1, "assistant", "通过消息工具发出的回复"),
            _rec("s", 9, 10, "user", "谢谢"),
        ]
        merged, lost, _ = _guard("openclaw", old, new, records)
        self.assertEqual(len(lost), 1)
        self.assertEqual(merged, _join("### Kai / Telegram Session s", _msg(9, 0, "Henry", "问一下"),
                                       _msg(9, 1, "Kai", "通过消息工具发出的回复"),
                                       _msg(9, 2, "Kai", "旧的文字回复"), _msg(9, 10, "Henry", "谢谢")))

    def test_manual_openclaw_block_is_never_left_behind(self):
        manual = (
            "<!-- openclaw-manual-begin channel=telegram source=henry-paste -->\n"
            "### Kai / Telegram (supplied by Henry)\n\n"
            "[8/13/26 4:42 AM] Henry: 在吗\n"
            "<!-- openclaw-manual-end -->"
        )
        old = _join(manual, "### Kai / WeChat Session w", _msg(22, 0, "Henry", "你好"))
        new = _join("### Kai / WeChat Session w", _msg(22, 0, "Henry", "你好"))
        merged, lost, _ = _guard("openclaw", old, new, [])
        self.assertEqual(len(lost), 1)
        self.assertEqual(merged, old)

    def test_hook_fallback_blocks_keep_their_own_lifecycle(self):
        fallback = _join(CODEX_THREAD, "> hook-fallback-turn: turn-1", _msg(23, 0, "Henry", "晚安"))
        old = _join(CODEX_THREAD, _msg(22, 0, "Henry", "今天"), fallback.rstrip("\n"))
        new = _join(CODEX_THREAD, _msg(22, 0, "Henry", "今天"), _msg(22, 59, "Henry", "晚安"))
        self.assertEqual(_guard("codex", old, new), (new, [], []))

    def test_web_conversation_is_rebuilt_with_its_source_line(self):
        heading = "### ChatGPT Web Conversation g-2 - 旧对话"
        old = _join(heading, "Source: <https://chatgpt.com/c/g-2>", _msg(8, 0, "Henry", "旧问题"),
                    "### ChatGPT Web Conversation g-3 - 新对话", "Source: <https://chatgpt.com/c/g-3>",
                    _msg(20, 0, "Henry", "新问题"))
        new = _join("### ChatGPT Web Conversation g-3 - 新对话", "Source: <https://chatgpt.com/c/g-3>",
                    _msg(20, 0, "Henry", "新问题"))
        merged, lost, _ = _guard("chatgpt-web", old, new, [_rec("g-3", 20, 0, "user", "新问题")])
        self.assertEqual(len(lost), 1)
        self.assertEqual(merged, old)


class TestSourceRecords(unittest.TestCase):
    def test_codex_records_include_filtered_messages_and_subagent_threads(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            day_dir = sessions / "2026" / "08" / "13"
            day_dir.mkdir(parents=True)
            for name, source in (("main", "user"), ("helper", "subagent")):
                thread = f"{name}-thread"
                rows = [
                    {"type": "session_meta", "payload": {"id": thread, "thread_source": source}},
                    {"type": "response_item", "timestamp": _ts(9, 0), "payload": {
                        "type": "message", "role": "user",
                        "content": [{"type": "input_text", "text": "<environment_context>x</environment_context>"}]}},
                    {"type": "response_item", "timestamp": _ts(9, 1), "payload": {
                        "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "好"}]}},
                    {"type": "response_item", "timestamp": _ts(9, 2), "payload": {"type": "reasoning"}},
                ]
                (day_dir / f"rollout-{name}.jsonl").write_text(
                    "\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            with patch.object(copilot, "CODEX_SESSIONS_DIR", sessions):
                records = copilot.codex_day_source_records(DAY)
        self.assertEqual(sorted((r[0], r[2], r[3]) for r in records), [
            ("helper-thread", "assistant", "好"),
            ("helper-thread", "user", "<environment_context>x</environment_context>"),
            ("main-thread", "assistant", "好"),
            ("main-thread", "user", "<environment_context>x</environment_context>"),
        ])

    def test_claude_code_records_include_runtime_notices(self):
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp)
            rows = [
                {"type": "user", "timestamp": _ts(9, 0), "isMeta": True,
                 "message": {"content": [{"type": "text", "text": "注入的说明"}]}},
                {"type": "user", "timestamp": _ts(9, 1), "message": {"content": "<task-notification>x</task-notification>"}},
                {"type": "assistant", "timestamp": _ts(9, 2), "message": {"content": [
                    {"type": "thinking", "thinking": "不算"}, {"type": "text", "text": "回答"}]}},
                {"type": "user", "timestamp": "2026-08-12T09:00:00+08:00", "message": {"content": "前一天"}},
            ]
            (projects / "s1.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
            records = copilot.claude_code_day_source_records(DAY, projects)
        self.assertEqual([(r[0], r[2], r[3]) for r in records], [
            ("s1", "user", "注入的说明"),
            ("s1", "user", "<task-notification>x</task-notification>"),
            ("s1", "assistant", "回答"),
        ])

    def test_openclaw_records_count_text_and_each_send(self):
        rows = [
            {"type": "message", "timestamp": _ts(9, 0), "message": {"role": "assistant", "content": [
                {"type": "text", "text": "先说一句"},
                {"type": "toolCall", "name": "message", "arguments": {"action": "send", "message": "第一行\\n第二行"}},
                {"type": "toolCall", "name": "exec", "arguments": {"message": "不是发给人的"}},
            ]}},
            {"type": "message", "timestamp": _ts(9, 1), "message": {
                "role": "user", "content": "定时任务提示", "__openclaw": {"senderIsOwner": False}}},
        ]
        jsonl = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
        records = copilot.openclaw_day_source_records(DAY, [("s", jsonl)])
        self.assertEqual([(r[2], r[3]) for r in records], [
            ("assistant", "先说一句"),
            ("assistant", "第一行 第二行"),
            ("user", "定时任务提示"),
        ])

    def test_web_records_cover_every_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            (store / "claude").mkdir()
            (store / "claude" / "c-1.json").write_text(json.dumps({"id": "c-1", "conversation": {
                "current_leaf_message_uuid": "b",
                "chat_messages": [
                    {"uuid": "a", "sender": "human", "created_at": _ts(9, 0), "content": [{"type": "text", "text": "旧分支"}]},
                    {"uuid": "b", "sender": "human", "created_at": _ts(9, 5), "content": [{"type": "text", "text": "新分支"}]},
                ],
            }}), encoding="utf-8")
            records = copilot.web_chat_day_source_records("claude", DAY, store)
        self.assertEqual(sorted(r[3] for r in records), ["新分支", "旧分支"])

    def test_renderer_records_include_selected_text(self):
        ts_ms = datetime(2026, 8, 13, 9, 0).timestamp() * 1000
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / "history.json"
            history.write_text(json.dumps([{"sessionId": "r1", "messages": [{
                "role": "user", "timestamp": ts_ms, "displayContent": "我喜欢这句",
                "contextAttachments": [{"type": "editor-selection", "text": "被选中的句子"}],
            }]}], ensure_ascii=False), encoding="utf-8")
            records = copilot.life_claude_renderer_day_source_records(DAY, history)
        self.assertEqual(records, [("r1", "8/13/26 9:00 AM", "user", "我喜欢这句 被选中的句子")])


class TestWritebackKeepsLostMessages(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.journal = self.root / "journal" / "2026" / "08" / "2026-08-13.md"
        self.journal.parent.mkdir(parents=True)
        self.journal.write_text("# 2026-08-13\n\n## 💬 From Kai\n", encoding="utf-8")
        self.trace = self.root / "journal" / "ai-conversations" / "2026" / "08" / "2026-08-13-codex-trace.md"
        self.trace.parent.mkdir(parents=True)
        self.old = _join(CODEX_THREAD, _msg(9, 0, "Henry", "被回滚的问题"), _msg(9, 5, "Henry", "保留的问题"))
        self.trace.write_text(_trace_file("codex", self.old), encoding="utf-8")
        self.patchers = [
            patch.object(copilot, "ROOT", self.root),
            patch.object(copilot, "JOURNAL_DIR", self.root / "journal"),
            patch.object(copilot, "AI_CONVERSATIONS_DIR", self.root / "journal" / "ai-conversations"),
            patch.object(copilot, "export_codex_day_transcript",
                         return_value=_join(CODEX_THREAD, _msg(9, 5, "Henry", "保留的问题"))),
            patch.object(copilot, "codex_day_source_records",
                         return_value=[_rec(CODEX_ID, 9, 5, "user", "保留的问题")]),
            patch.object(copilot, "export_life_claude_renderer_day_transcript", return_value=("", 0, 0)),
            patch.object(copilot, "export_claude_code_day_transcript", return_value=("", 0, 0)),
            patch.object(copilot, "export_openclaw_day_transcript", return_value=("", 0, 0)),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def test_writeback_keeps_lost_messages_and_says_so(self):
        output = io.StringIO()
        with redirect_stdout(output):
            result = copilot.writeback_ai_day(DAY)
        self.assertEqual(self.trace.read_text(encoding="utf-8"), "\n".join([
            "---",
            "date: 2026-08-13",
            "source: codex",
            "generated_by: scripts/copilot.py writeback-ai-day",
            "---",
            "",
            "# 2026-08-13 Codex Trace",
            "",
            self.old.rstrip("\n"),
        ]))
        self.assertIn("WARNING: kept 1 message(s)", output.getvalue())
        self.assertIn("--force", output.getvalue())
        self.assertEqual(result["kept_lost_messages"], {"codex": 1})

    def test_force_allows_a_deliberate_shrink(self):
        output = io.StringIO()
        with redirect_stdout(output):
            result = copilot.writeback_ai_day(DAY, force=True)
        self.assertNotIn("被回滚的问题", self.trace.read_text(encoding="utf-8"))
        self.assertIn("--force dropped 1 message(s)", output.getvalue())
        self.assertEqual(result["kept_lost_messages"], {})

    def test_cli_passes_force_and_the_bedtime_hook_never_does(self):
        parser = copilot.build_parser()
        self.assertFalse(parser.parse_args(["writeback-ai-day", "--date", "2026-08-13"]).force)
        with patch.object(copilot, "writeback_ai_day", return_value={"journal": "j"}) as run, \
             redirect_stdout(io.StringIO()):
            copilot.cmd_writeback_ai_day(parser.parse_args(["writeback-ai-day", "--date", "2026-08-13", "--force"]))
            self.assertTrue(run.call_args.kwargs["force"])
            hook_input = self.root / "hook.json"
            hook_input.write_text(json.dumps({"date": "2026-08-13"}), encoding="utf-8")
            copilot.cmd_finalize_ai_day(SimpleNamespace(hook_input_file=str(hook_input), date=None))
            self.assertFalse(run.call_args.kwargs.get("force", False))

    def test_openclaw_is_checked_against_the_sessions_the_export_read(self):
        openclaw_trace = self.trace.with_name("2026-08-13-openclaw-trace.md")
        kept_session = _join("### Kai / Telegram Session gone-session", _msg(8, 0, "Henry", "早上的对话"))
        openclaw_trace.write_text(_trace_file("openclaw", kept_session), encoding="utf-8")
        files = {
            "sessions.json": json.dumps({"agent:main:telegram:direct:100": {"sessionId": "live-session"}}),
            "live-session.jsonl": json.dumps({"type": "message", "timestamp": _ts(20, 0), "message": {
                "role": "user", "content": "晚上的对话", "__openclaw": {"senderIsOwner": True}}}, ensure_ascii=False),
        }
        self.patchers[-1].stop()
        self.patchers.pop()
        read_one = lambda path, *a, **k: files[path.rsplit("/", 1)[-1]]
        with patch.object(copilot, "read_openclaw_remote_text", side_effect=read_one), \
             patch.object(
                 copilot,
                 "read_openclaw_remote_texts",
                 side_effect=lambda paths, **k: {path: read_one(path) for path in paths},
             ), \
             patch.object(copilot, "list_openclaw_remote_direct_session_paths", return_value=[]), \
             redirect_stdout(io.StringIO()):
            result = copilot.writeback_ai_day(DAY)
        text = openclaw_trace.read_text(encoding="utf-8")
        self.assertIn("早上的对话", text)
        self.assertIn("晚上的对话", text)
        self.assertLess(text.index("早上的对话"), text.index("晚上的对话"))
        self.assertEqual(result["kept_lost_messages"], {"codex": 1, "openclaw": 1})


if __name__ == "__main__":
    unittest.main()
