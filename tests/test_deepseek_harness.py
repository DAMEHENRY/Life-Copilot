import json
from datetime import date, datetime, timezone

from scripts import copilot


def test_session_keeps_user_and_visible_assistant_text_after_inherited_history():
    stamp = datetime(2026, 11, 17, 4, tzinfo=timezone.utc)
    day = date(2026, 11, 17)

    def event(kind, **data):
        return {"type": kind, "data": data, "time": int(stamp.timestamp() * 1000)}

    question = [{"type": "text", "text": "question"}]
    rows = [
        {"type": "session", "version": 4, "id": "session-test", "isSeeded": True},
        event("user/message", content=question, source={"kind": "user"}),
        event("session/end-seed", inherited=1),
        event("session/title", title="Fixture"),
        event("user/message", content=question, source={"kind": "user"}),
        event("user/message", content=question, source={"kind": "tool-jobs"}),
        event("assistant/message", message={"content": [
            {"type": "reasoning", "text": "hidden"},
            {"type": "tool-call", "text": "hidden"},
            {"type": "text", "text": "visible answer"},
        ]}),
        event("tool/result", content=[{"type": "text", "text": "hidden"}]),
    ]
    data = "\n".join(json.dumps(row) for row in rows).encode()
    assert copilot.deepseek_harness_session(data, day) == (
        "session-test", "Fixture", [(stamp, "user", "question"), (stamp, "assistant", "visible answer")]
    )
