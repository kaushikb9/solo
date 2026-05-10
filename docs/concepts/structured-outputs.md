# Structured outputs

## What problem this solves

LLMs produce free-form text. When you want a *machine-readable* answer — a category label, a score, a list of fields — free-form text is a tax: you parse it, the parser breaks on a comma, you regex harder, you give up. Structured outputs make the model emit JSON that already conforms to a schema you define, so you skip the parsing fight entirely.

## The core idea

You declare a schema (in solo: a Pydantic `BaseModel`). You hand it to the SDK as `response_format`. The provider does two things: (1) injects schema-aware instructions into the prompt, and (2) constrains decoding so the output is valid JSON for that schema. You get back a typed object, not a string. If the schema says `priority: Literal["low", "medium", "high"]`, the model literally cannot return `"urgent"` — the provider rejects tokens that would make the JSON invalid.

```python
class ClassifyResult(BaseModel):
    kind: Literal["idea", "soft_task", "hard_task", "note"]
    summary: str
    priority: Literal["low", "medium", "high"]

result = await client.structured("classifier", ClassifyResult, model=..., vars=...)
# result is a ClassifyResult — type-checked, validated.
```

This is structurally different from "tell the LLM to output JSON and hope." It also subsumes a lot of what frameworks call *tool use* — a tool call is just a structured output with a name and arguments.

## How solo uses it

`LLMClient.structured` (`src/solo/llm.py:103`) wraps `client.beta.chat.completions.parse`, which is the OpenAI SDK's typed-response endpoint. The classifier (`src/solo/classifier.py`) defines `ClassifyResult` and calls `structured("classifier", ClassifyResult, …)`. No JSON parsing in solo's code.

## Common gotchas

- **Provider drift.** OpenRouter brokers many backends. Some implement structured outputs natively, some emulate them. solo's `tests/test_classifier_live.py` exists partly to catch this — if a backend silently degrades to "JSON-ish text," the test will surface it.
- **Schema-prompt mismatch.** Your prompt and your schema both convey expected behavior. Keep them in sync — don't list four categories in the prompt and three in the `Literal`.
- **Refusals look like errors.** When the model refuses or fails to fit the schema, the SDK raises. Wrap accordingly. solo's `LLMClient` writes an `error` row to `llm_calls` and re-raises; `classify_pending` then catches and bumps the retry counter.
- **Cost.** Structured outputs constrain decoding; this can slow generation slightly but rarely costs more tokens than equivalent free-form prompting.

## Further reading

- OpenAI docs: <https://platform.openai.com/docs/guides/structured-outputs>
- OpenRouter docs: <https://openrouter.ai/docs/structured-outputs>
- Pydantic `Literal` types: <https://docs.pydantic.dev/latest/concepts/types/>
