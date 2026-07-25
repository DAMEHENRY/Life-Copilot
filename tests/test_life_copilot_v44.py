"""Regression tests for merged Chat capture, bedtime close, and evolution."""

from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import copilot


MINIMAL_DIARY = textwrap.dedent("""\
    #diary
    # 📅 2026-07-25
    ## 💭 Thoughts & Reflections

    手写内容。

    ## 💬 From Kai

    ## What Life Copilot Said
""")


class TestMergedChatCapture(unittest.TestCase):
    def test_insert_and_incremental_update_are_idempotent(self):
        first = copilot.upsert_chat_capture(
            MINIMAL_DIARY,
            date(2026, 7, 25),
            "第一段经历。",
        )
        second = copilot.upsert_chat_capture(
            first,
            date(2026, 7, 25),
            "第一段经历。\n\n后来又补充了一段。",
        )
        self.assertEqual(second.count("capture-id: chat-capture-2026-07-25"), 1)
        self.assertEqual(second.count("capture-end: chat-capture-2026-07-25"), 1)
        self.assertNotIn("第一段经历。\n\n### 对话补记", second)
        self.assertIn("后来又补充了一段。", second)

    def test_update_preserves_handwritten_and_other_sections(self):
        first = copilot.upsert_chat_capture(
            MINIMAL_DIARY,
            date(2026, 7, 25),
            "系统合并内容。",
        )
        updated = copilot.upsert_chat_capture(
            first,
            date(2026, 7, 25),
            "更新后的系统合并内容。",
        )
        self.assertIn("手写内容。", updated)
        self.assertIn("## What Life Copilot Said", updated)
        self.assertNotIn("\n系统合并内容。\n\n", updated)

    def test_analysis_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Copilot analysis"):
            copilot.upsert_chat_capture(
                MINIMAL_DIARY,
                date(2026, 7, 25),
                "## 🧭 Copilot 建议\n你今天应该复盘。",
            )


class TestBedtimeRecognition(unittest.TestCase):
    def test_direct_equivalent_requests_trigger(self):
        prompts = [
            "请用一句有趣且出乎意料的话给我晚安",
            "那就跟我说一句晚安吧",
            "睡了，晚安",
            "Tell me good night in one surprising sentence.",
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertTrue(copilot.is_bedtime_close_prompt(prompt))

    def test_meta_discussion_and_quotes_do_not_trigger(self):
        prompts = [
            "我们来讨论晚安功能怎么触发",
            "我在引用别人说晚安",
            "测试晚安触发条件是否可靠",
            "The bedtime feature should store good night messages.",
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertFalse(copilot.is_bedtime_close_prompt(prompt))


class TestFinalDailyArchive(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.journal_dir = self.root / "journal"
        self.trace_dir = self.journal_dir / "ai-conversations"
        self.templates = self.root / "templates"
        self.templates.mkdir()
        (self.templates / "daily-log.md").write_text(
            MINIMAL_DIARY.replace("2026-07-25", "{{date:YYYY-MM-DD}}"),
            encoding="utf-8",
        )
        self.patchers = [
            patch.object(copilot, "ROOT", self.root),
            patch.object(copilot, "JOURNAL_DIR", self.journal_dir),
            patch.object(copilot, "AI_CONVERSATIONS_DIR", self.trace_dir),
            patch.object(copilot, "TEMPLATES_DIR", self.templates),
            patch.object(copilot, "export_codex_day_transcript", return_value=""),
            patch.object(
                copilot,
                "export_life_claude_renderer_day_transcript",
                return_value=("", 0, 0),
            ),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def test_missing_diary_and_rollout_delay_use_verified_fallback(self):
        payload = {
            "session_id": "session-a",
            "turn_id": "turn-9",
            "date": "2026-07-25",
            "timestamp": "2026-07-25T23:15:00+08:00",
            "prompt": "请用一句有趣且出乎意料的话给我晚安",
            "last_assistant_message": "月亮今晚替你的闹钟值夜班，晚安。",
        }
        first = copilot.writeback_ai_day(
            date(2026, 7, 25),
            create_journal=True,
            hook_payload=payload,
        )
        second = copilot.writeback_ai_day(
            date(2026, 7, 25),
            create_journal=True,
            hook_payload=payload,
        )
        self.assertTrue(first["fallback_used"])
        self.assertFalse(second["fallback_used"])
        trace = Path(first["codex_trace"]).read_text(encoding="utf-8")
        journal = Path(first["journal"]).read_text(encoding="utf-8")
        self.assertIn(payload["prompt"], trace)
        self.assertIn(payload["last_assistant_message"], trace)
        self.assertIn("turn-9", trace)
        self.assertEqual(journal.count("[[2026-07-25-codex-trace]]"), 1)

    def test_existing_duplicate_links_are_normalized(self):
        journal = self.journal_dir / "2026" / "07" / "2026-07-25.md"
        journal.parent.mkdir(parents=True)
        journal.write_text(
            MINIMAL_DIARY.replace(
                "## 💬 From Kai",
                "## 💬 From Kai\n\n"
                "- [[2026-07-25-codex-trace]]：old\n"
                "- [[2026-07-25-codex-trace]]：duplicate",
            ),
            encoding="utf-8",
        )
        payload = {
            "session_id": "session-b",
            "turn_id": "turn-b",
            "prompt": "跟我说晚安吧",
            "last_assistant_message": "把今天折成纸船交给夜色，晚安。",
        }
        copilot.writeback_ai_day(
            date(2026, 7, 25),
            create_journal=True,
            hook_payload=payload,
        )
        self.assertEqual(
            journal.read_text(encoding="utf-8").count(
                "[[2026-07-25-codex-trace]]"
            ),
            1,
        )

    def test_partial_rollout_does_not_duplicate_the_user_message(self):
        prompt = "请跟我说一句晚安"
        copilot.export_codex_day_transcript.return_value = (
            f"### Codex Thread session-partial\n\n"
            f"[7/25/26 11:15 PM] Henry: {prompt}\n"
        )
        payload = {
            "session_id": "session-partial",
            "turn_id": "turn-partial",
            "prompt": prompt,
            "last_assistant_message": "让枕头替你保管今天没解决的问题，晚安。",
        }
        result = copilot.writeback_ai_day(
            date(2026, 7, 25),
            create_journal=True,
            hook_payload=payload,
        )
        trace = Path(result["codex_trace"]).read_text(encoding="utf-8")
        self.assertEqual(trace.count(prompt), 1)
        self.assertIn(payload["last_assistant_message"], trace)

    def test_concurrent_delayed_turns_survive_until_real_rollout_arrives(self):
        first = {
            "session_id": "session-1",
            "turn_id": "turn-1",
            "prompt": "跟我说晚安吧",
            "last_assistant_message": "第一句晚安。",
        }
        second = {
            "session_id": "session-2",
            "turn_id": "turn-2",
            "prompt": "请用一句意外的话给我晚安",
            "last_assistant_message": "第二句晚安。",
        }
        result = copilot.writeback_ai_day(
            date(2026, 7, 25), create_journal=True, hook_payload=first
        )
        copilot.writeback_ai_day(
            date(2026, 7, 25), create_journal=True, hook_payload=second
        )
        trace = Path(result["codex_trace"]).read_text(encoding="utf-8")
        self.assertIn("turn-1", trace)
        self.assertIn("turn-2", trace)
        self.assertIn("第一句晚安。", trace)
        self.assertIn("第二句晚安。", trace)

        copilot.export_codex_day_transcript.return_value = "\n\n".join([
            "### Codex Thread session-1\n\n"
            "[7/25/26 11:10 PM] Henry: 跟我说晚安吧\n\n"
            "[7/25/26 11:10 PM] Codex: 第一句晚安。",
            "### Codex Thread session-2\n\n"
            "[7/25/26 11:12 PM] Henry: 请用一句意外的话给我晚安\n\n"
            "[7/25/26 11:12 PM] Codex: 第二句晚安。",
        ])
        copilot.writeback_ai_day(
            date(2026, 7, 25), create_journal=True, hook_payload=second
        )
        refreshed = Path(result["codex_trace"]).read_text(encoding="utf-8")
        self.assertNotIn("hook-fallback-turn", refreshed)


class EvolutionFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.prompts = self.root / "prompts"
        self.prompts.mkdir()
        self.target = self.prompts / "chat-mode.md"
        self.current = (
            "普通 Chat 不立即写入\nwriteback-chat-capture\nDiary Mode\nold\n"
        )
        self.target.write_text(self.current, encoding="utf-8")
        self.candidates = self.root / "journal" / "system-evolution-candidates"
        self.candidates.mkdir(parents=True)
        self.golden = self.root / "evals" / "golden.jsonl"
        self.golden.parent.mkdir()
        self.golden.write_text(
            '{"id":"hard-a","hard":true}\n{"id":"hard-b","hard":true}\n',
            encoding="utf-8",
        )
        self.ledger = self.root / "journal" / "system-evolution.jsonl"
        self.patchers = [
            patch.object(copilot, "ROOT", self.root),
            patch.object(
                copilot,
                "SYSTEM_EVOLUTION_CANDIDATES_DIR",
                self.candidates,
            ),
            patch.object(copilot, "SYSTEM_EVOLUTION_GOLDEN_CASES", self.golden),
            patch.object(copilot, "SYSTEM_EVOLUTION_LEDGER", self.ledger),
            patch.object(
                copilot,
                "SYSTEM_EVOLUTION_EDITABLE_TARGETS",
                {
                    "L0": {"prompts/chat-mode.md"},
                    "L1": {"prompts/evolution-policy.md"},
                },
            ),
            patch.object(
                copilot,
                "SYSTEM_EVOLUTION_REQUIRED_PHRASES",
                {
                    "prompts/chat-mode.md": (
                        "普通 Chat 不立即写入",
                        "writeback-chat-capture",
                        "Diary Mode",
                    )
                },
            ),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def make_candidate(self, **updates) -> Path:
        content = self.candidates / "candidate-content.md"
        content.write_text(
            "普通 Chat 不立即写入\nwriteback-chat-capture\nDiary Mode\nimproved\n",
            encoding="utf-8",
        )
        manifest = {
            "id": "chat-capture-threshold",
            "layer": "L0",
            "target": "prompts/chat-mode.md",
            "model": "gpt-test",
            "explicit_system_design_request": True,
            "evidence": [{"date": "2026-07-25", "ref": "[[2026-07-25]]"}],
            "before_sha256": copilot.sha256_text(self.current),
            "candidate_content_file": content.name,
            "evaluation": {
                "hard_constraints_passed": True,
                "target_improved": True,
                "regressions": [],
                "passed_golden_cases": ["hard-a", "hard-b"],
                "recent_trace_refs": ["[[2026-07-25-codex-trace]]"],
            },
        }
        manifest.update(updates)
        path = self.candidates / "chat-capture-threshold.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path


class TestEvolutionGuards(EvolutionFixture):
    def test_valid_l0_candidate_passes(self):
        candidate, target, proposed = copilot.validate_system_rule_candidate(
            self.make_candidate()
        )
        self.assertEqual(candidate["layer"], "L0")
        self.assertEqual(target, self.target)
        self.assertIn("improved", proposed)

    def test_l2_candidate_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "L2 is immutable"):
            copilot.validate_system_rule_candidate(
                self.make_candidate(layer="L2", target="AGENTS.md")
            )

    def test_missing_hard_case_is_rejected(self):
        evaluation = {
            "hard_constraints_passed": True,
            "target_improved": True,
            "regressions": [],
            "passed_golden_cases": ["hard-a"],
            "recent_trace_refs": ["trace"],
        }
        with self.assertRaisesRegex(ValueError, "hard-b"):
            copilot.validate_system_rule_candidate(
                self.make_candidate(evaluation=evaluation)
            )

    def test_dirty_target_pauses_promotion(self):
        with patch.object(copilot, "git_target_is_dirty", return_value=True):
            with self.assertRaisesRegex(ValueError, "promotion paused"):
                copilot.cmd_promote_system_rule(
                    SimpleNamespace(candidate_file=str(self.make_candidate()))
                )
        events = copilot.read_system_evolution_ledger()
        self.assertEqual(events[-1]["status"], "dirty_target")

    def test_model_change_triggers_review_and_recent_same_model_is_noop(self):
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        self.ledger.write_text(
            json.dumps({
                "event": "compatibility_audit",
                "status": "complete",
                "date": "2026-07-24",
                "model": "gpt-old",
            }) + "\n",
            encoding="utf-8",
        )
        with patch("builtins.print"):
            copilot.cmd_audit_system_rules(SimpleNamespace(
                date="2026-07-25",
                model="gpt-old",
                candidate_file=None,
                record_noop=False,
                json=True,
            ))
        before = len(copilot.read_system_evolution_ledger())
        with patch("builtins.print"):
            copilot.cmd_audit_system_rules(SimpleNamespace(
                date="2026-07-25",
                model="gpt-new",
                candidate_file=None,
                record_noop=False,
                json=True,
            ))
        records = copilot.read_system_evolution_ledger()
        self.assertEqual(len(records), before + 1)
        self.assertIn("model_slug_changed", records[-1]["reasons"])

    def test_complete_review_requires_all_hard_cases_and_real_trace(self):
        evidence = self.root / "review.json"
        evidence.write_text(json.dumps({
            "hard_constraints_passed": True,
            "regressions": [],
            "passed_golden_cases": ["hard-a", "hard-b"],
            "recent_trace_refs": ["[[2026-07-25-codex-trace]]"],
        }), encoding="utf-8")
        with patch("builtins.print"):
            copilot.cmd_audit_system_rules(SimpleNamespace(
                date="2026-07-25",
                model="gpt-new",
                complete_review=True,
                review_evidence_file=str(evidence),
                candidate_file=None,
                record_noop=False,
                json=True,
            ))
        record = copilot.read_system_evolution_ledger()[-1]
        self.assertEqual(record["event"], "compatibility_audit")
        self.assertEqual(record["status"], "complete")

    def test_expired_probation_becomes_stable(self):
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        self.ledger.write_text(json.dumps({
            "event": "promotion",
            "candidate_id": "old-candidate",
            "status": "probation",
            "probation_until": "2026-07-24",
            "target": "prompts/chat-mode.md",
            "commit": "abc",
        }) + "\n", encoding="utf-8")
        with patch("builtins.print"):
            copilot.cmd_audit_system_rules(SimpleNamespace(
                date="2026-07-25",
                model="gpt-new",
                complete_review=False,
                review_evidence_file=None,
                candidate_file=None,
                record_noop=False,
                json=True,
            ))
        states = copilot.latest_candidate_states(
            copilot.read_system_evolution_ledger()
        )
        self.assertEqual(states["old-candidate"]["status"], "stable")


if __name__ == "__main__":
    unittest.main()
