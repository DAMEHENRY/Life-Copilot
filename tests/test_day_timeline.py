"""Day timeline: the day's traces on one time axis, rebuilt from the trace files."""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from scripts import copilot

DAY = date(2026, 8, 13)
CODEX_A = "### Codex Thread aaaaaaaa-1111-4111-8111-111111111111"
CODEX_B = "### Codex Thread bbbbbbbb-1111-4111-8111-111111111111"
CLAUDE = "### Claude Code Session cccccccc-1111-4111-8111-111111111111 - Lecture notes"
KAI = "### Kai / Telegram Session dddddddd-1111-4111-8111-111111111111"


def _msg(hour: int, minute: int, speaker: str, text: str, day: int = 13) -> str:
    stamp = datetime(2026, 8, day, hour, minute).astimezone().isoformat()
    return f"[{copilot.format_chat_timestamp(stamp)}] {speaker}: {text}"


def _join(*parts: str) -> str:
    return "\n\n".join(parts) + "\n"


class TimelineCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.trace_dir = self.root / "journal" / "ai-conversations" / "2026" / "08"
        self.trace_dir.mkdir(parents=True)
        self.patchers = [
            patch.object(copilot, "ROOT", self.root),
            patch.object(copilot, "JOURNAL_DIR", self.root / "journal"),
            patch.object(copilot, "AI_CONVERSATIONS_DIR", self.root / "journal" / "ai-conversations"),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def trace(self, source: str, *parts: str) -> Path:
        path = self.trace_dir / f"2026-08-13-{source}-trace.md"
        path.write_text(
            f"---\ndate: 2026-08-13\nsource: {source}\n---\n\n# 2026-08-13 {source} Trace\n\n" + _join(*parts),
            encoding="utf-8",
        )
        return path

    def rows(self, heading: str = "## Timeline") -> list[str]:
        text = copilot.render_day_timeline(DAY)
        section = text.split(heading + "\n\n", 1)[1].split("\n\n", 1)[0]
        return section.strip().split("\n")


class TestSegments(TimelineCase):
    def test_sources_are_merged_into_one_order_with_quiet_stretches(self) -> None:
        self.trace(
            "codex",
            CODEX_A,
            _msg(8, 1, "Henry", "start of the lecture"),
            _msg(8, 2, "Codex", "ready"),
            _msg(8, 20, "Henry", "a question"),
            _msg(8, 21, "Codex", "an answer"),
            _msg(9, 0, "Henry", "after the break"),
            CODEX_B,
            _msg(8, 10, "Henry", "a side question"),
            _msg(8, 10, "Codex", "a side answer"),
        )
        self.trace(
            "claude-code",
            CLAUDE,
            _msg(11, 30, "Henry", "tidy the notes"),
            _msg(11, 40, "Claude", "done"),
        )
        self.assertEqual(self.rows(), [
            "- 08:01–08:21 · Codex aaaaaaaa · Henry 2, AI 2 · `start of the lecture`",
            "- 08:10 · Codex bbbbbbbb · Henry 1, AI 1 · `a side question`",
            # 39 minutes of silence in one session: a new segment, but not a quiet stretch.
            "- 09:00 · Codex aaaaaaaa · Henry 1, AI 0 · `after the break`",
            "- 09:00–11:30 · no messages for 2h 30m",
            "- 11:30–11:40 · Claude Code cccccccc `Lecture notes` · Henry 1, AI 1 · `tidy the notes`",
        ])
        self.assertEqual(self.rows("## Side by side"), ["- 08:10 · Codex aaaaaaaa + Codex bbbbbbbb"])
        self.assertIn(
            "First message 08:01, last 11:40. 3 sessions in 4 segments; "
            "33m inside a segment, 1m of it in two or more at once.",
            copilot.render_day_timeline(DAY),
        )

    def test_a_silence_of_exactly_the_gap_stays_in_the_segment(self) -> None:
        self.trace(
            "codex", CODEX_A,
            _msg(9, 0, "Henry", "one"),
            _msg(9, 20, "Henry", "two"),
            _msg(9, 41, "Henry", "three"),
        )
        self.assertEqual(self.rows(), [
            "- 09:00–09:20 · Codex aaaaaaaa · Henry 2, AI 0 · `one`",
            "- 09:41 · Codex aaaaaaaa · Henry 1, AI 0 · `three`",
        ])
        self.assertNotIn("## Side by side", copilot.render_day_timeline(DAY))

    def test_every_message_lands_in_exactly_one_segment(self) -> None:
        self.trace(
            "codex", CODEX_A,
            *[_msg(8 + n // 4, (n * 13) % 60, "Henry" if n % 2 else "Codex", f"m{n}") for n in range(40)],
        )
        messages = copilot.day_timeline_messages(DAY)
        segments = copilot.day_timeline_segments(messages)
        self.assertEqual(len(messages), 40)
        self.assertEqual(sum(s["henry"] + s["assistant"] for s in segments), 40)

    def test_a_reply_without_a_question_is_named_as_such(self) -> None:
        self.trace("codex", CODEX_A, _msg(22, 0, "Codex", "the long job finished"))
        self.assertEqual(self.rows(), ["- 22:00 · Codex aaaaaaaa · Henry 0, AI 1 · (reply only)"])

    def test_a_message_dated_another_day_shows_its_date(self) -> None:
        self.trace(
            "codex", CODEX_A,
            _msg(23, 50, "Henry", "late"),
            _msg(0, 5, "Codex", "past midnight", day=14),
        )
        self.assertEqual(self.rows(), ["- 23:50–08-14 00:05 · Codex aaaaaaaa · Henry 1, AI 1 · `late`"])


class TestParsing(TimelineCase):
    def test_only_session_headings_and_message_lines_count(self) -> None:
        self.trace(
            "chatgpt-web",
            "### ChatGPT Web Conversation eeeeeeee-1111 - Volume indicator",
            "Source: <https://chatgpt.com/c/eeeeeeee-1111>",
            _msg(14, 30, "Henry", "what does the abbreviation stand for"),
            _msg(14, 30, "ChatGPT", "It stands for this."),
            "### 1. Formula",  # a heading inside the answer
            "### Codex Thread <id> - <title>",  # the heading format, quoted in an answer
            "Henry: a line from a pasted chat, with no timestamp",
            _msg(14, 31, "Someone", "a pasted line that only looks like a message"),
        )
        self.assertEqual(self.rows(), [
            "- 14:30 · ChatGPT Web eeeeeeee `Volume indicator` · Henry 1, AI 1 · "
            "`what does the abbreviation stand for`",
        ])

    def test_older_sources_and_a_pasted_record_are_read_too(self) -> None:
        self.trace(
            "claudian",
            "### Claudian Session ffffffff-1111 - find the earlier note...",
            _msg(10, 0, "Henry", "find the earlier note on this"),
            _msg(10, 1, "Claudian", "found it"),
        )
        self.trace(
            "gemini-web",
            "### Gemini Web Conversation 0123456789abcdef - measuring a shoulder",
            _msg(12, 0, "Henry", "how is it measured"),
            _msg(12, 1, "Gemini", "like this"),
        )
        self.trace(
            "chatgpt-web",
            "### ChatGPT Web Conversation 99999999-1111 [Health] - sleep data",
            _msg(16, 30, "Henry", "compare the two weeks"),
        )
        self.trace(
            "openclaw",
            "<!-- openclaw-manual-begin channel=telegram source=henry-paste -->",
            "### Kai / Telegram（a record Henry pasted）",
            "[8/13/26 4:42 AM] Henry: are you there",
            "[8/13/26 4:43 AM] Kai: yes",
            "<!-- openclaw-manual-end -->",
            KAI,
            _msg(16, 0, "Henry", "back from the pool"),
        )
        self.assertEqual(self.rows(), [
            "- 04:42–04:43 · Kai manual · Henry 1, AI 1 · `are you there`",
            "- 04:43–10:00 · no messages for 5h 17m",
            # The title is the first message again, so it is left out.
            "- 10:00–10:01 · Claudian ffffffff · Henry 1, AI 1 · `find the earlier note on this`",
            "- 10:01–12:00 · no messages for 1h 59m",
            "- 12:00–12:01 · Gemini Web 01234567 `measuring a shoulder` · Henry 1, AI 1 · `how is it measured`",
            "- 12:01–16:00 · no messages for 3h 59m",
            "- 16:00 · Kai / Telegram dddddddd · Henry 1, AI 0 · `back from the pool`",
            "- 16:30 · ChatGPT Web 99999999 `[Health] sleep data` · Henry 1, AI 0 · `compare the two weeks`",
        ])


class TestTopic(unittest.TestCase):
    def test_what_the_client_put_in_the_turn_is_stepped_over(self) -> None:
        self.assertEqual(
            copilot.timeline_topic('<external_codex_apps_open_page>{"page_id":null}</external_codex_apps_open_page>'),
            "",
        )
        self.assertEqual(
            copilot.timeline_topic(
                '[Image]\n\n<pasted_content id="b1">\nsomeone\n2026/08/13 11:59\nhello\n'
                '</pasted_content id="b1">\n\n<!-- reply 1 -->\nis this a good moment to ask'
            ),
            "`is this a good moment to ask`",
        )
        self.assertEqual(
            copilot.timeline_topic(
                "# Files mentioned by the user:\n\n## shot.png: /tmp/shot.png\nImage attachment: true\n\n"
                "## My request:\nwhy did the traffic leave by that node\n\n[Image: shot.png]"
            ),
            "`why did the traffic leave by that node`",
        )

    def test_a_topic_is_one_short_line_that_links_nothing(self) -> None:
        topic = copilot.timeline_topic("see [[2026-08-12]] and `code` | " + "长" * 80 + "\nsecond line")
        self.assertTrue(topic.startswith("`see [[2026-08-12]] and 'code' | 长"))
        self.assertTrue(topic.endswith("…`"))
        self.assertEqual(len(topic), copilot.TIMELINE_TOPIC_CHARS + 3)
        self.assertEqual(topic.count("`"), 2)


class TestWrite(TimelineCase):
    def test_same_traces_give_the_same_file_and_it_is_not_a_trace(self) -> None:
        trace = self.trace("codex", CODEX_A, _msg(9, 0, "Henry", "one"))
        before = trace.read_bytes()
        out = io.StringIO()
        with redirect_stdout(out):
            path = copilot.write_day_timeline(DAY)
            first = path.read_bytes()
            self.assertEqual(copilot.write_day_timeline(DAY), path)
        self.assertEqual(path.name, "2026-08-13-timeline.md")
        self.assertEqual(path.read_bytes(), first)
        # Written once: the second run found nothing to change.
        self.assertEqual(out.getvalue().count("wrote:"), 1)
        self.assertEqual(trace.read_bytes(), before)
        self.assertEqual(copilot.day_trace_paths(DAY), [trace])

    def test_a_day_without_timestamps_writes_nothing(self) -> None:
        self.trace("codex", CODEX_A, "Henry: an old record without times")
        self.assertIsNone(copilot.write_day_timeline(DAY))
        self.assertFalse(copilot.day_timeline_path(DAY).exists())

    def test_the_read_plan_puts_the_timeline_before_the_traces(self) -> None:
        self.trace("codex", CODEX_A, _msg(9, 0, "Henry", "one"))
        with redirect_stdout(io.StringIO()):
            path = copilot.write_day_timeline(DAY)
        lines = copilot.format_read_budget(copilot.audit_read_budget(DAY), include_ok=False)
        size = len(path.read_bytes())
        start = lines.index(
            "Day timeline, read before the traces (an index of them, not evidence): "
            f"journal/ai-conversations/2026/08/2026-08-13-timeline.md  {size:,} bytes"
        )
        # It is not one of the traces, and not one of the other must-read files either.
        self.assertTrue(lines[start + 1].startswith(
            "Traces to read before the analysis, in journal/ai-conversations/2026/08/ (1 file, "
        ))
        self.assertEqual(sum("timeline" in line for line in lines), 1)


class TestWritebackAiDay(TimelineCase):
    def setUp(self) -> None:
        super().setUp()
        journal = self.root / "journal" / "2026" / "08" / "2026-08-13.md"
        journal.parent.mkdir(parents=True)
        journal.write_text("# 2026-08-13\n\n## 💬 From Kai\n", encoding="utf-8")
        self.journal = journal
        extra = [
            patch.object(copilot, "export_codex_day_transcript",
                         return_value=_join(CODEX_A, _msg(9, 5, "Henry", "a question"))),
            patch.object(copilot, "codex_day_source_records", return_value=[]),
            patch.object(copilot, "export_life_claude_renderer_day_transcript", return_value=("", 0, 0)),
            patch.object(copilot, "export_claude_code_day_transcript",
                         return_value=(_join(CLAUDE, _msg(9, 6, "Henry", "another")), 1, 1)),
            patch.object(copilot, "claude_code_day_source_records", return_value=[]),
            patch.object(copilot, "export_openclaw_day_transcript", return_value=("", 0, 0)),
        ]
        for patcher in extra:
            patcher.start()
        self.patchers += extra

    def test_the_archive_writes_the_timeline_and_adds_no_from_kai_link(self) -> None:
        with redirect_stdout(io.StringIO()):
            result = copilot.writeback_ai_day(DAY)
        path = copilot.day_timeline_path(DAY)
        self.assertEqual(result["timeline"], str(path))
        text = path.read_text(encoding="utf-8")
        self.assertIn("- 09:05 · Codex aaaaaaaa · Henry 1, AI 0 · `a question`", text)
        self.assertIn("- 09:06 · Claude Code cccccccc `Lecture notes` · Henry 1, AI 0 · `another`", text)
        # From Kai keeps one link per source; the timeline is not a source.
        self.assertNotIn("timeline", self.journal.read_text(encoding="utf-8"))

    def test_a_timeline_failure_does_not_fail_the_archive(self) -> None:
        out = io.StringIO()
        with patch.object(copilot, "render_day_timeline", side_effect=RuntimeError("boom")), \
                redirect_stdout(out):
            result = copilot.writeback_ai_day(DAY)
        self.assertEqual(result["timeline"], "")
        self.assertIn("warning: day timeline not written (boom)", out.getvalue())
        self.assertTrue((self.trace_dir / "2026-08-13-codex-trace.md").exists())
        self.assertIn("[[2026-08-13-codex-trace]]", self.journal.read_text(encoding="utf-8"))


class TestPastedChats(TimelineCase):
    """WeChat messages in Henry's part of the diary go on the same axis."""

    def diary(self, *parts: str) -> None:
        journal = self.root / "journal" / "2026" / "08" / "2026-08-13.md"
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text("\n".join(parts) + "\n", encoding="utf-8")

    @staticmethod
    def chat(*messages: tuple) -> str:
        return "\n".join(f"{who}\n2026/08/{day} {clock}\n{text}\n" for who, day, clock, text in messages)

    def test_a_chat_fills_what_the_traces_call_a_silence(self) -> None:
        self.trace(
            "codex", CODEX_A,
            _msg(9, 0, "Henry", "a question"),
            _msg(12, 55, "Henry", "is this a good moment to ask"),
            _msg(13, 5, "Codex", "yes"),
        )
        self.diary(
            "## 💭 Thoughts & Reflections",
            "",
            # Pasted straight after a sentence: the first name ends that sentence.
            "We talked at noon and it went well.Henry",
            "2026/08/13 11:59",
            "look at this view",
            "",
            self.chat(
                ("Rowan", 13, "12:07", "where is that"),
                ("Henry", 13, "12:08", "by the lake"),
                ("Rowan", 13, "12:59", "[Sticker]"),
                ("Henry", 13, "13:00", "coming over"),
            ),
            "Then I went back to work and wrote this paragraph after the chat.",
        )
        self.assertEqual(self.rows(), [
            "- 09:00 · Codex aaaaaaaa · Henry 1, AI 0 · `a question`",
            "- 09:00–11:59 · no messages for 2h 59m",
            "- 11:59–12:08 · WeChat `Rowan` · Henry 2, others 1 · `look at this view`",
            "- 12:55–13:05 · Codex aaaaaaaa · Henry 1, AI 1 · `is this a good moment to ask`",
            "- 12:59–13:00 · WeChat `Rowan` · Henry 1, others 1 · `coming over`",
        ])
        self.assertEqual(self.rows("## Side by side"), ["- 12:59–13:00 · Codex aaaaaaaa + WeChat `Rowan`"])
        self.assertIn(
            "First message 09:00, last 13:05. 1 session in 2 segments; 22m inside a segment, "
            "2m of it in two or more at once. WeChat: 5 messages from the diary in 2 segments.",
            copilot.render_day_timeline(DAY),
        )

    def test_a_time_that_runs_backwards_starts_another_chat(self) -> None:
        self.diary(
            "## 💭 Thoughts & Reflections",
            "",
            self.chat(("Henry", 13, "21:30", "see you tomorrow"), ("Rowan", 13, "21:31", "see you")),
            self.chat(
                ("Ash", 13, "21:25", "who is in"),
                ("Birch", 13, "21:25", "me"),
                ("Cedar", 13, "21:26", "me too"),
                ("Dale", 13, "21:26", ""),  # a picture: the export leaves the text out
                ("Ash", 13, "21:27", "good"),
            ),
        )
        self.assertEqual(self.rows(), [
            "- 21:25–21:27 · WeChat `Ash`, `Birch`, `Cedar` +1 · Henry 0, others 5 · (no message from Henry)",
            "- 21:30–21:31 · WeChat `Rowan` · Henry 1, others 1 · `see you tomorrow`",
        ])
        # Two chats, one after the other: nothing ran side by side.
        self.assertNotIn("## Side by side", copilot.render_day_timeline(DAY))

    def test_only_this_days_messages_in_henrys_own_text_count(self) -> None:
        self.diary(
            "## 💭 Thoughts & Reflections",
            "",
            self.chat(
                ("Rowan", 12, "23:50", "an older message quoted for context"),
                ("Henry", 13, "08:00", "good morning"),
                ("Henry", 13, "08:00", "good morning"),  # pasted twice
            ),
            "### 对话补记",
            "",
            "> [!info] 对话转写",
            "> capture-id: chat-capture-2026-08-13",
            "> Rowan",
            "> 2026/08/13 10:00",
            "> a chat Copilot transcribed, not Henry's own paste",
            "> capture-end: chat-capture-2026-08-13",
            "",
            "## What Life Copilot Said",
            "",
            self.chat(("Rowan", 13, "11:00", "quoted inside the analysis")),
        )
        text = copilot.render_day_timeline(DAY)
        self.assertEqual(self.rows(), ["- 08:00 · WeChat · Henry 1, others 0 · `good morning`"])
        self.assertIn(
            "First message 08:00, last 08:00. 1m inside a segment. WeChat: 1 message from the diary "
            "in 1 segment. Pasted WeChat messages dated another day, left out: 1.",
            text,
        )

    def test_a_sender_that_cannot_be_read_is_reported(self) -> None:
        self.diary(
            "A long sentence that runs straight into a name nobody else in this diary has, Quill",
            "2026/08/13 15:00",
            "hello",
        )
        text = copilot.render_day_timeline(DAY)
        self.assertEqual(self.rows(), ["- 15:00 · WeChat · Henry 0, others 1 · (no message from Henry)"])
        self.assertIn("WeChat messages whose sender could not be read: 1.", text)

    def test_a_date_line_in_prose_is_not_a_message(self) -> None:
        self.diary("On 2026/08/13 10:00 I left the house.", "", "2026/08/13", "10:00")
        self.assertEqual(copilot.render_day_timeline(DAY), "")


class TestEarlierDay(TimelineCase):
    """A day is archived when its analysis starts; the next night's run takes it along."""

    def day(self, day: int, *messages: str) -> Path:
        journal = self.root / "journal" / "2026" / "08" / f"2026-08-{day:02d}.md"
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text("# day\n\n## 💬 From Kai\n", encoding="utf-8")
        path = self.trace_dir / f"2026-08-{day:02d}-codex-trace.md"
        path.write_text(_join(CODEX_A, *messages), encoding="utf-8")
        return path

    def test_only_a_run_on_today_or_yesterday_takes_an_earlier_day_along(self) -> None:
        self.day(10, _msg(9, 0, "Henry", "one", day=10))
        self.day(12, _msg(9, 0, "Henry", "one", day=12))
        # The 11th has no trace, so the day before it is the latest archived one.
        self.assertEqual(copilot.earlier_archived_day(date(2026, 8, 12), today=date(2026, 8, 12)), date(2026, 8, 10))
        self.assertEqual(copilot.earlier_archived_day(DAY, today=date(2026, 8, 14)), date(2026, 8, 12))
        # A deliberate rerun of an older date touches no other day.
        self.assertIsNone(copilot.earlier_archived_day(DAY, today=date(2026, 8, 15)))
        self.assertIsNone(copilot.earlier_archived_day(date(2026, 8, 20), today=date(2026, 8, 20)))

    def test_it_reports_what_the_second_archive_added(self) -> None:
        path = self.day(12, _msg(22, 0, "Henry", "before the analysis", day=12))

        def later(day, **options):
            self.assertEqual(day, date(2026, 8, 12))
            self.assertEqual(options, {"web_chats": True, "web_chats_synced": True})
            path.write_text(
                path.read_text(encoding="utf-8") + _join(
                    _msg(23, 0, "Henry", "after it", day=12), _msg(23, 1, "Codex", "noted", day=12)),
                encoding="utf-8",
            )

        with patch.object(copilot, "writeback_ai_day", side_effect=later):
            line = copilot.archive_earlier_day_again(DAY, today=DAY, web_chats=True, web_chats_synced=True)
        self.assertEqual(
            line,
            "Earlier day 2026-08-12 archived again: 2 messages sent after its last archive are now in its traces.",
        )
        with patch.object(copilot, "writeback_ai_day"):
            self.assertEqual(
                copilot.archive_earlier_day_again(DAY, today=DAY),
                "Earlier day 2026-08-12 archived again: nothing new.",
            )
        with patch.object(copilot, "writeback_ai_day", side_effect=RuntimeError("no link")):
            self.assertTrue(copilot.archive_earlier_day_again(DAY, today=DAY).startswith(
                "WARNING: could not archive 2026-08-12 again (no link)"
            ))

    def test_the_command_never_forces_the_earlier_day(self) -> None:
        self.day(12, _msg(22, 0, "Henry", "before the analysis", day=12))
        self.day(13, _msg(9, 0, "Henry", "today"))
        parser = copilot.build_parser()
        args = parser.parse_args(["writeback-ai-day", "--date", "2026-08-13", "--force"])
        out = io.StringIO()
        real_earlier = copilot.earlier_archived_day
        with patch.object(copilot, "writeback_ai_day", return_value={"journal": "j"}) as run, \
                patch.object(copilot, "earlier_archived_day", side_effect=lambda target, today=None: real_earlier(target, DAY)), \
                redirect_stdout(out):
            copilot.cmd_writeback_ai_day(args)
        first, second = run.call_args_list
        self.assertEqual(first.args, (DAY,))
        self.assertTrue(first.kwargs["force"])
        self.assertEqual(second.args, (date(2026, 8, 12),))
        self.assertNotIn("force", second.kwargs)
        self.assertNotIn("create_journal", second.kwargs)
        self.assertTrue(second.kwargs["web_chats_synced"])
        lines = out.getvalue().splitlines()
        self.assertEqual(lines[0], "Earlier day 2026-08-12 archived again: nothing new.")
        self.assertTrue(lines[1].startswith("Read budget:"))
        self.assertEqual(lines[-1], "j")


if __name__ == "__main__":
    unittest.main()
