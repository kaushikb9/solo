# Concepts

Primers on AI/agent concepts that solo uses, written for someone new to AI engineering. The point is to **compound learning**: every implementation step that introduces a new concept gets a doc here, in the same change.

## How to write one

Use the `/concept <topic>` slash command, or this structure manually:

```
# <topic>

## What problem this solves
Plain language. No jargon. One paragraph.

## The core idea
Explain as if to a smart friend who's new to AI. Concrete examples.

## How solo uses it
Link to the file/function in this repo. Show the smallest working example.

## Common gotchas
What trips people up.

## Further reading
Only links you've actually verified.
```

Length: 300–500 words. Concrete > exhaustive.

## Index

- [LLM API basics](llm-api-basics.md) — chat completions, messages, tokens, the openai SDK shape
- [Observability via a trace table](observability-trace-table.md) — why a row per LLM call beats logs/metrics
- [Structured outputs](structured-outputs.md) — Pydantic schemas as the contract between code and model
- [Evaluating LLM outputs](evaluating-llm-outputs.md) — eval harnesses, classifier metrics, why prose is hard to grade
