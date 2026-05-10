"""Live integration test — hits a real OpenRouter model.

Skipped unless OPENROUTER_API_KEY is set in the environment.
Run manually with: OPENROUTER_API_KEY=... uv run pytest tests/test_llm_live.py -v
"""

import os
import sqlite3

import pytest

LIVE = os.getenv("OPENROUTER_API_KEY")
pytestmark = pytest.mark.skipif(not LIVE, reason="OPENROUTER_API_KEY not set")


@pytest.mark.asyncio
async def test_chat_against_real_openrouter(tmp_path):
    from solo.llm import LLMClient
    from solo.trace import ensure_schema

    db_path = tmp_path / "live.db"
    conn = sqlite3.connect(str(db_path))
    ensure_schema(conn)
    conn.close()

    client = LLMClient(api_key=LIVE, db_path=db_path)
    result = await client.chat(
        [{"role": "user", "content": "Reply with the single word: ok"}],
        model="minimax/minimax-m2.7",
    )

    assert isinstance(result, str)
    assert len(result) > 0

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM llm_calls").fetchone()
    conn.close()

    assert row["status"] == "ok"
    assert row["model"] == "minimax/minimax-m2.7"
    assert row["input_tokens"] is not None and row["input_tokens"] > 0
    assert row["output_tokens"] is not None and row["output_tokens"] > 0
    assert row["cost_usd"] is not None and row["cost_usd"] > 0
    assert row["latency_ms"] > 0
