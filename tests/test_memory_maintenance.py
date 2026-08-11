"""Focused tests for autonomous, transactional memory maintenance."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

from scripts import copilot as copilot_module
from scripts.copilot import cmd_maintain_memory, maintain_memory_text


MEMORY = """## Memory Governance (v2)
- Stable Profile: stable.

## Stable Profile
- Identity: tester.

## Active Hypotheses (Last 30 Days)
- [2026-08-01] reading: First version. Evidence: [[2026-08-01]].
- [2026-08-02] body: Keep this. Evidence: [[2026-08-02]].

## Canonical Memories
- [2026-07-01] canonical: Existing truth. Evidence: [[2026-07-01]].
"""

ARCHIVE = """## Legacy Stream (Pre-v2)
"""


def _manifest(*operations: dict) -> dict:
    return {"operations": list(operations)}


def test_noop_changes_nothing():
    updated, archive, changes = maintain_memory_text(
        MEMORY,
        ARCHIVE,
        _manifest({"action": "no-op", "reason": "no durable signal"}),
        "2026-08-10",
    )
    assert updated == MEMORY
    assert archive == ARCHIVE
    assert changes == [{"action": "no-op", "changed": False, "reason": "no durable signal"}]


def test_add_active_is_idempotent():
    manifest = _manifest({
        "action": "add-active",
        "kind": "relationship",
        "content": "A new hypothesis. Evidence: [[2026-08-10]].",
    })
    first, archive, _ = maintain_memory_text(MEMORY, ARCHIVE, manifest, "2026-08-10")
    second, _, changes = maintain_memory_text(first, archive, manifest, "2026-08-10")
    assert first == second
    assert first.count("A new hypothesis") == 1
    assert changes[0]["changed"] is False


def test_replace_active_archives_previous_version():
    updated, archive, changes = maintain_memory_text(
        MEMORY,
        ARCHIVE,
        _manifest({
            "action": "replace-active",
            "match": "[2026-08-01] reading: First version. Evidence: [[2026-08-01]].",
            "kind": "reading",
            "content": "Revised version with new support from [[2026-08-10]].",
            "reason": "new evidence refined the hypothesis",
        }),
        "2026-08-10",
    )
    assert "First version" not in updated
    assert "[2026-08-10] reading: Revised version" in updated
    assert "First version" in archive
    assert "action=replace-active" in archive
    assert changes[0]["changed"] is True


def test_promote_moves_active_to_canonical_once():
    operation = {
        "action": "promote-canonical",
        "match": "[2026-08-01] reading: First version. Evidence: [[2026-08-01]].",
        "kind": "canonical",
        "content": "Validated reading principle. Evidence: [[2026-08-01]][[2026-08-10]].",
        "reason": "validated across independent contexts",
    }
    first, archive, _ = maintain_memory_text(MEMORY, ARCHIVE, _manifest(operation), "2026-08-10")
    second, archive2, changes = maintain_memory_text(first, archive, _manifest(operation), "2026-08-10")
    active = first.split("## Active Hypotheses (Last 30 Days)", 1)[1].split("## Canonical Memories", 1)[0]
    canonical = first.split("## Canonical Memories", 1)[1]
    assert "First version" not in active
    assert canonical.count("Validated reading principle") == 1
    assert first == second
    assert archive == archive2
    assert changes[0]["changed"] is False


def test_archive_removes_without_deleting_history():
    updated, archive, _ = maintain_memory_text(
        MEMORY,
        ARCHIVE,
        _manifest({
            "action": "archive-active",
            "match": "[2026-08-01] reading: First version. Evidence: [[2026-08-01]].",
            "reason": "hypothesis expired without new support",
        }),
        "2026-08-10",
    )
    assert "First version" not in updated
    assert "First version" in archive
    assert "action=archive-active" in archive


def test_archive_is_idempotent_on_repeat():
    operation = {
        "action": "archive-active",
        "match": "[2026-08-01] reading: First version. Evidence: [[2026-08-01]].",
        "reason": "hypothesis expired without new support",
    }
    first, archive, _ = maintain_memory_text(MEMORY, ARCHIVE, _manifest(operation), "2026-08-10")
    second, archive2, changes = maintain_memory_text(first, archive, _manifest(operation), "2026-08-10")
    assert first == second
    assert archive == archive2
    assert changes[0]["changed"] is False


def test_missing_compare_and_swap_target_fails_without_partial_result():
    try:
        maintain_memory_text(
            MEMORY,
            ARCHIVE,
            _manifest(
                {
                    "action": "add-active",
                    "kind": "new",
                    "content": "Would have been added. Evidence: [[2026-08-10]].",
                },
                {
                    "action": "replace-active",
                    "match": "[2026-01-01] missing: Not present.",
                    "kind": "missing",
                    "content": "Replacement. Evidence: [[2026-08-10]].",
                    "reason": "test conflict",
                },
            ),
            "2026-08-10",
        )
        assert False, "Expected compare-and-swap failure"
    except ValueError as exc:
        assert "not found" in str(exc)


def test_automatic_entry_requires_dated_provenance():
    try:
        maintain_memory_text(
            MEMORY,
            ARCHIVE,
            _manifest({
                "action": "add-active",
                "kind": "unsafe",
                "content": "No evidence link.",
            }),
            "2026-08-10",
        )
        assert False, "Expected provenance validation failure"
    except ValueError as exc:
        assert "dated wikilink" in str(exc)


def test_command_dry_run_does_not_write(monkeypatch, tmp_path, capsys):
    memory_path = tmp_path / "memory.md"
    archive_path = tmp_path / "memory-archive.md"
    manifest_path = tmp_path / "maintenance.json"
    memory_path.write_text(MEMORY, encoding="utf-8")
    archive_path.write_text(ARCHIVE, encoding="utf-8")
    manifest_path.write_text(json.dumps(_manifest({
        "action": "add-active",
        "kind": "test",
        "content": "Dry run. Evidence: [[2026-08-10]].",
    })), encoding="utf-8")
    monkeypatch.setattr(copilot_module, "MEMORY_FILE", memory_path)
    monkeypatch.setattr(copilot_module, "MEMORY_ARCHIVE_FILE", archive_path)

    cmd_maintain_memory(SimpleNamespace(
        date="2026-08-10",
        input_file=str(manifest_path),
        dry_run=True,
    ))

    result = json.loads(capsys.readouterr().out)
    assert result["changed_operations"] == 1
    assert "Dry run" not in memory_path.read_text(encoding="utf-8")


def test_command_applies_validated_transaction(monkeypatch, tmp_path, capsys):
    memory_path = tmp_path / "memory.md"
    archive_path = tmp_path / "memory-archive.md"
    manifest_path = tmp_path / "maintenance.json"
    memory_path.write_text(MEMORY, encoding="utf-8")
    archive_path.write_text(ARCHIVE, encoding="utf-8")
    manifest_path.write_text(json.dumps(_manifest({
        "action": "replace-active",
        "match": "[2026-08-01] reading: First version. Evidence: [[2026-08-01]].",
        "kind": "reading",
        "content": "Updated safely with [[2026-08-10]].",
        "reason": "new support",
    })), encoding="utf-8")
    monkeypatch.setattr(copilot_module, "MEMORY_FILE", memory_path)
    monkeypatch.setattr(copilot_module, "MEMORY_ARCHIVE_FILE", archive_path)

    cmd_maintain_memory(SimpleNamespace(
        date="2026-08-10",
        input_file=str(manifest_path),
        dry_run=False,
    ))

    result = json.loads(capsys.readouterr().out)
    assert result["changed_operations"] == 1
    assert "Updated safely" in memory_path.read_text(encoding="utf-8")
    assert "First version" in archive_path.read_text(encoding="utf-8")
