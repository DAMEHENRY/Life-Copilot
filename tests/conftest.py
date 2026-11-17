from pathlib import Path

import pytest

from scripts import copilot


@pytest.fixture(autouse=True)
def isolate_deepseek_harness_store(monkeypatch):
    monkeypatch.setattr(copilot, "DEEPSEEK_HARNESS_SESSIONS_DIR", Path("/nonexistent/deepseek-harness"))
