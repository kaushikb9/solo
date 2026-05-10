"""LLMClient — single observable entry point for every LLM call in solo.

All LLM calls go through this module. Every call writes one row to the
llm_calls trace table.
"""

import json
import time
from datetime import UTC, datetime
from pathlib import Path

from openai import AsyncOpenAI
from pydantic import BaseModel

from solo import trace
from solo.db import get_connection

# Verified at openrouter.ai/models — update on drift.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # (input_per_1m_tokens_usd, output_per_1m_tokens_usd)
    "minimax/minimax-m2.7":  (0.30, 1.20),
    "moonshotai/kimi-k2.5":  (0.44, 2.00),
    "moonshotai/kimi-k2.6":  (0.74, 3.49),
}


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        return None
    in_price, out_price = pricing
    return (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price


class LLMClient:
    def __init__(self, api_key: str, db_path: Path):
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is required")
        self._db_path = Path(db_path)
        # Ensure the llm_calls table exists; trace writes assume it.
        conn = get_connection(str(self._db_path))
        try:
            trace.ensure_schema(conn)
        finally:
            conn.close()
        self._client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str,
        prompt_name: str | None = None,
    ) -> str:
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        prompt_text = json.dumps(messages)
        start = time.monotonic()

        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=messages,
            )
        except Exception as exc:
            self._write_trace(
                ts=ts,
                model=model,
                prompt_name=prompt_name,
                prompt_text=prompt_text,
                response_text=None,
                input_tokens=None,
                output_tokens=None,
                cost_usd=None,
                latency_ms=int((time.monotonic() - start) * 1000),
                status="error",
                error=str(exc),
            )
            raise

        latency_ms = int((time.monotonic() - start) * 1000)
        content = response.choices[0].message.content or ""
        in_tok = response.usage.prompt_tokens
        out_tok = response.usage.completion_tokens

        self._write_trace(
            ts=ts,
            model=model,
            prompt_name=prompt_name,
            prompt_text=prompt_text,
            response_text=content,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=compute_cost(model, in_tok, out_tok),
            latency_ms=latency_ms,
            status="ok",
            error=None,
        )
        return content

    async def structured(
        self,
        prompt_name: str,
        schema: type[BaseModel],
        *,
        model: str,
        vars: dict | None = None,
    ) -> BaseModel:
        from solo import prompts

        rendered = prompts.render(prompt_name, **(vars or {}))
        messages = [{"role": "user", "content": rendered}]
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        prompt_text = json.dumps(messages)
        start = time.monotonic()

        try:
            response = await self._client.beta.chat.completions.parse(
                model=model,
                messages=messages,
                response_format=schema,
            )
        except Exception as exc:
            self._write_trace(
                ts=ts,
                model=model,
                prompt_name=prompt_name,
                prompt_text=prompt_text,
                response_text=None,
                input_tokens=None,
                output_tokens=None,
                cost_usd=None,
                latency_ms=int((time.monotonic() - start) * 1000),
                status="error",
                error=str(exc),
            )
            raise

        latency_ms = int((time.monotonic() - start) * 1000)
        parsed = response.choices[0].message.parsed
        in_tok = response.usage.prompt_tokens
        out_tok = response.usage.completion_tokens

        self._write_trace(
            ts=ts,
            model=model,
            prompt_name=prompt_name,
            prompt_text=prompt_text,
            response_text=response.choices[0].message.content or "",
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=compute_cost(model, in_tok, out_tok),
            latency_ms=latency_ms,
            status="ok",
            error=None,
        )
        return parsed

    def _write_trace(self, **row) -> None:
        conn = get_connection(str(self._db_path))
        try:
            trace.record_call(conn, **row)
        finally:
            conn.close()
