import json
import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    conn = sqlite3.connect(str(path))
    from solo.trace import ensure_schema

    ensure_schema(conn)
    conn.close()
    return path


def _mock_chat_response(content: str, input_tokens: int = 5, output_tokens: int = 2):
    """Build a mock object shaped like openai's ChatCompletion response."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    response.usage.prompt_tokens = input_tokens
    response.usage.completion_tokens = output_tokens
    return response


class TestChat:
    @pytest.mark.asyncio
    async def test_chat_returns_assistant_text(self, db_path, monkeypatch):
        from solo.llm import LLMClient

        client = LLMClient(api_key="test-key", db_path=db_path)
        mock_create = AsyncMock(return_value=_mock_chat_response("hello back"))
        monkeypatch.setattr(client._client.chat.completions, "create", mock_create)

        result = await client.chat(
            [{"role": "user", "content": "hi"}],
            model="minimax/minimax-m2.7",
        )
        assert result == "hello back"

    @pytest.mark.asyncio
    async def test_chat_writes_trace_row(self, db_path, monkeypatch):
        from solo.llm import LLMClient

        client = LLMClient(api_key="test-key", db_path=db_path)
        mock_create = AsyncMock(return_value=_mock_chat_response("hello back", 10, 4))
        monkeypatch.setattr(client._client.chat.completions, "create", mock_create)

        await client.chat(
            [{"role": "user", "content": "hi"}],
            model="minimax/minimax-m2.7",
            prompt_name="ad-hoc",
        )

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM llm_calls").fetchone()
        conn.close()

        assert row["model"] == "minimax/minimax-m2.7"
        assert row["prompt_name"] == "ad-hoc"
        assert row["status"] == "ok"
        assert row["response_text"] == "hello back"
        assert row["input_tokens"] == 10
        assert row["output_tokens"] == 4
        assert row["cost_usd"] == pytest.approx(10 / 1_000_000 * 0.30 + 4 / 1_000_000 * 1.20)
        assert row["latency_ms"] >= 0
        assert json.loads(row["prompt_text"]) == [{"role": "user", "content": "hi"}]

    @pytest.mark.asyncio
    async def test_chat_passes_correct_messages_to_sdk(self, db_path, monkeypatch):
        from solo.llm import LLMClient

        client = LLMClient(api_key="test-key", db_path=db_path)
        mock_create = AsyncMock(return_value=_mock_chat_response("ok"))
        monkeypatch.setattr(client._client.chat.completions, "create", mock_create)

        msgs = [{"role": "user", "content": "hello"}]
        await client.chat(msgs, model="minimax/minimax-m2.7")

        mock_create.assert_awaited_once()
        kwargs = mock_create.call_args.kwargs
        assert kwargs["messages"] == msgs
        assert kwargs["model"] == "minimax/minimax-m2.7"


class TestComputeCost:
    def test_known_model_returns_cost(self):
        from solo.llm import compute_cost

        # minimax/minimax-m2.7: $0.30 / $1.20 per M tokens
        # 1000 input + 500 output = 0.0003 + 0.0006 = 0.0009
        cost = compute_cost("minimax/minimax-m2.7", 1000, 500)
        assert cost == pytest.approx(0.0009)

    def test_unknown_model_returns_none(self):
        from solo.llm import compute_cost

        assert compute_cost("does/not-exist", 1000, 500) is None

    def test_zero_tokens_zero_cost(self):
        from solo.llm import compute_cost

        assert compute_cost("minimax/minimax-m2.7", 0, 0) == 0.0


class TestChatErrors:
    @pytest.mark.asyncio
    async def test_chat_writes_error_row_and_reraises(self, db_path, monkeypatch):
        from solo.llm import LLMClient

        client = LLMClient(api_key="test-key", db_path=db_path)
        mock_create = AsyncMock(side_effect=RuntimeError("boom"))
        monkeypatch.setattr(client._client.chat.completions, "create", mock_create)

        with pytest.raises(RuntimeError, match="boom"):
            await client.chat(
                [{"role": "user", "content": "hi"}],
                model="minimax/minimax-m2.7",
            )

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM llm_calls").fetchone()
        conn.close()

        assert row["status"] == "error"
        assert row["error"] == "boom"
        assert row["response_text"] is None
        assert row["cost_usd"] is None
        assert row["input_tokens"] is None
        assert row["latency_ms"] >= 0

    @pytest.mark.asyncio
    async def test_init_rejects_empty_api_key(self, db_path):
        from solo.llm import LLMClient

        with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
            LLMClient(api_key="", db_path=db_path)


class _ClassifyResult(BaseModel):
    category: str
    urgency: int


def _mock_parse_response(parsed_obj, input_tokens: int = 8, output_tokens: int = 5):
    """Build a mock shaped like client.beta.chat.completions.parse() response."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = parsed_obj
    response.choices[0].message.content = parsed_obj.model_dump_json()
    response.usage.prompt_tokens = input_tokens
    response.usage.completion_tokens = output_tokens
    return response


class TestStructured:
    @pytest.fixture
    def fake_prompts_dir(self, tmp_path, monkeypatch):
        prompts = tmp_path / "prompts"
        prompts.mkdir()
        (prompts / "classifier.md").write_text("Classify: {entry}")
        monkeypatch.setattr("solo.prompts.PROMPTS_DIR", prompts)
        return prompts

    @pytest.mark.asyncio
    async def test_structured_returns_parsed_pydantic(
        self, db_path, fake_prompts_dir, monkeypatch
    ):
        from solo.llm import LLMClient

        client = LLMClient(api_key="test-key", db_path=db_path)
        expected = _ClassifyResult(category="learning", urgency=2)
        mock_parse = AsyncMock(return_value=_mock_parse_response(expected))
        monkeypatch.setattr(client._client.beta.chat.completions, "parse", mock_parse)

        result = await client.structured(
            "classifier",
            schema=_ClassifyResult,
            model="minimax/minimax-m2.7",
            vars={"entry": "learn rust"},
        )
        assert result == expected

    @pytest.mark.asyncio
    async def test_structured_writes_trace_row_with_prompt_name(
        self, db_path, fake_prompts_dir, monkeypatch
    ):
        from solo.llm import LLMClient

        client = LLMClient(api_key="test-key", db_path=db_path)
        expected = _ClassifyResult(category="x", urgency=1)
        mock_parse = AsyncMock(return_value=_mock_parse_response(expected))
        monkeypatch.setattr(client._client.beta.chat.completions, "parse", mock_parse)

        await client.structured(
            "classifier",
            schema=_ClassifyResult,
            model="minimax/minimax-m2.7",
            vars={"entry": "learn rust"},
        )

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM llm_calls").fetchone()
        conn.close()

        assert row["prompt_name"] == "classifier"
        assert row["status"] == "ok"
        # prompt_text contains the rendered template wrapped in messages array
        msgs = json.loads(row["prompt_text"])
        assert any("learn rust" in m["content"] for m in msgs)

    @pytest.mark.asyncio
    async def test_structured_passes_response_format_to_sdk(
        self, db_path, fake_prompts_dir, monkeypatch
    ):
        from solo.llm import LLMClient

        client = LLMClient(api_key="test-key", db_path=db_path)
        expected = _ClassifyResult(category="x", urgency=1)
        mock_parse = AsyncMock(return_value=_mock_parse_response(expected))
        monkeypatch.setattr(client._client.beta.chat.completions, "parse", mock_parse)

        await client.structured(
            "classifier",
            schema=_ClassifyResult,
            model="minimax/minimax-m2.7",
            vars={"entry": "x"},
        )
        kwargs = mock_parse.call_args.kwargs
        assert kwargs["response_format"] is _ClassifyResult
        assert kwargs["model"] == "minimax/minimax-m2.7"


class TestStructuredErrors:
    @pytest.fixture
    def fake_prompts_dir(self, tmp_path, monkeypatch):
        prompts = tmp_path / "prompts"
        prompts.mkdir()
        (prompts / "classifier.md").write_text("Classify: {entry}")
        monkeypatch.setattr("solo.prompts.PROMPTS_DIR", prompts)
        return prompts

    @pytest.mark.asyncio
    async def test_structured_writes_error_row_and_reraises(
        self, db_path, fake_prompts_dir, monkeypatch
    ):
        from solo.llm import LLMClient

        client = LLMClient(api_key="test-key", db_path=db_path)
        mock_parse = AsyncMock(side_effect=RuntimeError("schema mismatch"))
        monkeypatch.setattr(client._client.beta.chat.completions, "parse", mock_parse)

        with pytest.raises(RuntimeError, match="schema mismatch"):
            await client.structured(
                "classifier",
                schema=_ClassifyResult,
                model="minimax/minimax-m2.7",
                vars={"entry": "x"},
            )

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM llm_calls").fetchone()
        conn.close()
        assert row["status"] == "error"
        assert row["error"] == "schema mismatch"
        assert row["prompt_name"] == "classifier"
