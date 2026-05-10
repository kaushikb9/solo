# 0002 — Three-module split: `llm.py` / `prompts.py` / `trace.py`

**Status:** accepted
**Date:** 2026-05-09

## Context

The slice-2 design needs three things: an LLM client, a prompt loader, and a trace-row writer. They're all small (~50–150 lines each). Two reasonable shapes:

1. **One module** (`llm.py`) doing all three. Smaller surface area, fewer files. Default YAGNI choice.
2. **Three modules**, one per responsibility. Larger surface, clearer boundaries.

This is a learning project — pedagogical clarity matters. A future eval harness (slice 5) will load prompts directly without going through `LLMClient`, so `prompts.py` will get a second consumer regardless.

## Decision

Three modules:

- `src/solo/trace.py` — `ensure_schema(conn)`, `record_call(conn, ...)`
- `src/solo/prompts.py` — `load(name)`, `render(name, **vars)`
- `src/solo/llm.py` — `LLMClient`, `MODEL_PRICING`, `compute_cost`

Each module has one job and a small interface. `LLMClient` composes the other two.

## Consequences

**Easier:**
- Each file is short and focused; explicit boundaries make the architecture readable.
- Eval harness in slice 5 can `from solo.prompts import load` without dragging in OpenAI deps.
- Tests are colocated with responsibility (`test_trace.py`, `test_prompts.py`, `test_llm.py`).

**Harder:**
- Three files instead of one. Marginally more navigation cost.
- A change that crosses two modules (e.g. adding a new field that flows from prompt → trace row) touches more files.

## Alternatives considered

- **One file** — rejected because the eval-harness consumer makes the prompts-loader split inevitable, and tracing is intrinsically separable from API calls.
- **Two files** (`llm.py` + `trace.py`, with prompts inlined in llm.py) — rejected for the same reason; `prompts.py` will be wanted standalone.
