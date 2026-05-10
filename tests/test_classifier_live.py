"""Live classifier integration test — hits a real OpenRouter model.

Skipped unless OPENROUTER_API_KEY is set.
Run manually: OPENROUTER_API_KEY=... uv run pytest tests/test_classifier_live.py -v
"""

import os

import pytest

LIVE = os.getenv("OPENROUTER_API_KEY")
pytestmark = pytest.mark.skipif(not LIVE, reason="OPENROUTER_API_KEY not set")

VALID_KINDS = {"idea", "soft_task", "hard_task", "note"}
VALID_PRIORITIES = {"low", "medium", "high"}


@pytest.mark.asyncio
async def test_classify_one_real_entry(tmp_path):
    from solo.classifier import classify_pending
    from solo.db import get_connection, insert_entry
    from solo.llm import LLMClient

    db_path = tmp_path / "live.db"
    conn = get_connection(str(db_path))
    rid = insert_entry(
        conn,
        raw_text="figure out a better hiring loop for senior engineers",
        telegram_chat_id=1,
        telegram_message_id=1,
        telegram_message_json="{}",
    )

    client = LLMClient(api_key=LIVE, db_path=db_path)
    n = await classify_pending(conn, client, model="minimax/minimax-m2.7")
    assert n == 1

    row = conn.execute("SELECT * FROM entries WHERE id=?", (rid,)).fetchone()
    assert row["kind"] in VALID_KINDS
    assert row["priority"] in VALID_PRIORITIES
    assert row["summary"] is not None and len(row["summary"]) <= 120
    assert row["classified"] == 1
    conn.close()
