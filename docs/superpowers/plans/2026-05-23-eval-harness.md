# Slice 5 — Classifier eval harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `evals/classify.jsonl` (15 hand-labeled seeds) + `scripts/eval.py` (sequential runner using `LLMClient.structured`) + `src/solo/evals.py` (pure scoring) — output a terminal table and a JSON sidecar to `evals/results/`.

**Architecture:** Pure scoring functions in `solo.evals` (no IO, no LLM); thin CLI in `scripts/eval.py` wiring `LLMClient` + scorer + JSON dump; cost/latency aggregation against the `llm_calls` trace table via a new `solo.trace.aggregate_range` helper.

**Tech Stack:** Python 3.12, `sqlite3` stdlib, `pytest`, `argparse`, existing `LLMClient` from slice 2, `ruff`.

**Spec:** [`docs/superpowers/specs/2026-05-23-eval-harness-design.md`](../specs/2026-05-23-eval-harness-design.md)

---

## Task 1: `solo.evals.score_kind` + `score_priority`

**Files:**
- Create: `src/solo/evals.py`
- Create: `tests/test_evals.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_evals.py`:

```python
def test_score_kind_match():
    from solo.evals import score_kind

    assert score_kind("idea", "idea") is True


def test_score_kind_mismatch():
    from solo.evals import score_kind

    assert score_kind("idea", "note") is False


def test_score_priority_exact_returns_distance_zero():
    from solo.evals import score_priority

    correct, distance = score_priority("high", "high")
    assert correct is True
    assert distance == 0


def test_score_priority_off_by_one():
    from solo.evals import score_priority

    correct, distance = score_priority("medium", "high")
    assert correct is False
    assert distance == 1


def test_score_priority_off_by_two():
    from solo.evals import score_priority

    correct, distance = score_priority("low", "high")
    assert correct is False
    assert distance == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_evals.py -v`
Expected: `ModuleNotFoundError: No module named 'solo.evals'`

- [ ] **Step 3: Write the implementation**

`src/solo/evals.py`:

```python
"""Classifier eval scoring — pure functions.

No IO, no LLM. Score per-row predictions against labeled ground truth,
then aggregate into a summary + confusion matrix.
"""

_PRIORITY_ORDER = {"low": 0, "medium": 1, "high": 2}


def score_kind(predicted: str, actual: str) -> bool:
    return predicted == actual


def score_priority(predicted: str, actual: str) -> tuple[bool, int]:
    """Returns (exact_match, ordinal_distance) on low<medium<high."""
    distance = abs(_PRIORITY_ORDER[predicted] - _PRIORITY_ORDER[actual])
    return distance == 0, distance
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_evals.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/solo/evals.py tests/test_evals.py
git commit -m "feat(evals): add per-row kind and priority scorers"
```

---

## Task 2: `solo.evals.build_confusion`

**Files:**
- Modify: `src/solo/evals.py`
- Modify: `tests/test_evals.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_evals.py`:

```python
def test_build_confusion_shape_and_counts():
    from solo.evals import build_confusion

    rows = [
        {"actual_kind": "idea",      "predicted_kind": "idea"},
        {"actual_kind": "idea",      "predicted_kind": "note"},
        {"actual_kind": "soft_task", "predicted_kind": "soft_task"},
        {"actual_kind": "hard_task", "predicted_kind": "hard_task"},
        {"actual_kind": "note",      "predicted_kind": "note"},
    ]
    m = build_confusion(rows)

    kinds = {"idea", "soft_task", "hard_task", "note"}
    assert set(m.keys()) == kinds
    for actual_row in m.values():
        assert set(actual_row.keys()) == kinds

    assert m["idea"]["idea"] == 1
    assert m["idea"]["note"] == 1
    assert m["soft_task"]["soft_task"] == 1
    assert m["hard_task"]["hard_task"] == 1
    assert m["note"]["note"] == 1
    assert m["soft_task"]["idea"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_evals.py::test_build_confusion_shape_and_counts -v`
Expected: `ImportError: cannot import name 'build_confusion'`

- [ ] **Step 3: Append implementation**

Append to `src/solo/evals.py`:

```python
_KINDS = ("idea", "soft_task", "hard_task", "note")


def build_confusion(rows: list[dict]) -> dict[str, dict[str, int]]:
    """Build a confusion matrix keyed by [actual_kind][predicted_kind] -> count."""
    matrix: dict[str, dict[str, int]] = {a: {p: 0 for p in _KINDS} for a in _KINDS}
    for row in rows:
        matrix[row["actual_kind"]][row["predicted_kind"]] += 1
    return matrix
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_evals.py::test_build_confusion_shape_and_counts -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/solo/evals.py tests/test_evals.py
git commit -m "feat(evals): add kind confusion matrix builder"
```

---

## Task 3: `solo.evals.summarize`

**Files:**
- Modify: `src/solo/evals.py`
- Modify: `tests/test_evals.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_evals.py`:

```python
def test_summarize_empty_returns_zeros():
    from solo.evals import summarize

    s = summarize([])
    assert s["total"] == 0
    assert s["kind_accuracy"] == 0.0
    assert s["priority_accuracy"] == 0.0
    assert s["priority_off_by_one"] == 0.0
    assert s["priority_off_by_two"] == 0.0
    assert s["confusion"] == {}


def test_summarize_computes_rates():
    from solo.evals import summarize

    rows = [
        {"actual_kind": "idea", "predicted_kind": "idea",
         "kind_correct": True, "priority_distance": 0},
        {"actual_kind": "idea", "predicted_kind": "note",
         "kind_correct": False, "priority_distance": 1},
        {"actual_kind": "soft_task", "predicted_kind": "soft_task",
         "kind_correct": True, "priority_distance": 2},
        {"actual_kind": "note", "predicted_kind": "note",
         "kind_correct": True, "priority_distance": 0},
    ]
    s = summarize(rows)
    assert s["total"] == 4
    assert s["kind_accuracy"] == 0.75
    assert s["priority_accuracy"] == 0.5
    assert s["priority_off_by_one"] == 0.25
    assert s["priority_off_by_two"] == 0.25


def test_summarize_includes_confusion():
    from solo.evals import summarize

    rows = [
        {"actual_kind": "idea", "predicted_kind": "note",
         "kind_correct": False, "priority_distance": 0},
    ]
    s = summarize(rows)
    assert s["confusion"]["idea"]["note"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_evals.py -v -k summarize`
Expected: 3 failures (ImportError).

- [ ] **Step 3: Append implementation**

Append to `src/solo/evals.py`:

```python
def summarize(rows: list[dict]) -> dict:
    """Aggregate per-row results into a summary dict. Pure; no rendering."""
    total = len(rows)
    if total == 0:
        return {
            "total": 0,
            "kind_accuracy": 0.0,
            "priority_accuracy": 0.0,
            "priority_off_by_one": 0.0,
            "priority_off_by_two": 0.0,
            "confusion": {},
        }
    kind_correct = sum(1 for r in rows if r["kind_correct"])
    p_exact = sum(1 for r in rows if r["priority_distance"] == 0)
    p_off_by_1 = sum(1 for r in rows if r["priority_distance"] == 1)
    p_off_by_2 = sum(1 for r in rows if r["priority_distance"] == 2)
    return {
        "total": total,
        "kind_accuracy": kind_correct / total,
        "priority_accuracy": p_exact / total,
        "priority_off_by_one": p_off_by_1 / total,
        "priority_off_by_two": p_off_by_2 / total,
        "confusion": build_confusion(rows),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_evals.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/solo/evals.py tests/test_evals.py
git commit -m "feat(evals): add summarize aggregator"
```

---

## Task 4: `solo.trace.aggregate_range` for cost/latency reporting

**Files:**
- Modify: `src/solo/trace.py`
- Modify: `tests/test_trace.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trace.py`:

```python
class TestAggregateRange:
    def test_aggregates_cost_and_latency_within_range(self, conn):
        from solo.trace import aggregate_range, record_call

        for i, latency in enumerate([100, 200, 300]):
            record_call(
                conn,
                ts=f"2026-05-23T10:00:{i:02d}Z",
                model="minimax/minimax-m2.7",
                prompt_name="classifier",
                prompt_text="x",
                response_text="y",
                input_tokens=10,
                output_tokens=5,
                cost_usd=0.0001,
                latency_ms=latency,
                status="ok",
                error=None,
            )

        ids = [r[0] for r in conn.execute("SELECT id FROM llm_calls ORDER BY id").fetchall()]
        out = aggregate_range(conn, id_min=ids[0], id_max=ids[-1])

        assert out["count"] == 3
        assert out["errors"] == 0
        assert abs(out["total_cost_usd"] - 0.0003) < 1e-9
        assert out["mean_latency_ms"] == 200

    def test_aggregate_range_empty_returns_zeros(self, conn):
        from solo.trace import aggregate_range

        out = aggregate_range(conn, id_min=1, id_max=1)
        assert out == {"count": 0, "errors": 0, "total_cost_usd": 0.0, "mean_latency_ms": 0}

    def test_aggregate_range_counts_errors(self, conn):
        from solo.trace import aggregate_range, record_call

        record_call(
            conn,
            ts="2026-05-23T10:00:00Z",
            model="minimax/minimax-m2.7",
            prompt_name="classifier",
            prompt_text="x",
            response_text=None,
            input_tokens=None,
            output_tokens=None,
            cost_usd=None,
            latency_ms=50,
            status="error",
            error="boom",
        )

        ids = [r[0] for r in conn.execute("SELECT id FROM llm_calls").fetchall()]
        out = aggregate_range(conn, id_min=ids[0], id_max=ids[0])
        assert out["count"] == 1
        assert out["errors"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_trace.py::TestAggregateRange -v`
Expected: `ImportError: cannot import name 'aggregate_range'`

- [ ] **Step 3: Append the implementation**

Append to `src/solo/trace.py`:

```python
def aggregate_range(
    conn: sqlite3.Connection, *, id_min: int, id_max: int
) -> dict:
    """Aggregate count/errors/cost/mean-latency over llm_calls in [id_min, id_max]."""
    row = conn.execute(
        """
        SELECT
            COUNT(*)                                              AS count,
            COALESCE(SUM(CASE WHEN status='error' THEN 1 ELSE 0 END), 0) AS errors,
            COALESCE(SUM(cost_usd), 0.0)                          AS total_cost_usd,
            COALESCE(AVG(latency_ms), 0)                          AS mean_latency_ms
        FROM llm_calls
        WHERE id BETWEEN ? AND ?
        """,
        (id_min, id_max),
    ).fetchone()
    return {
        "count": int(row[0] or 0),
        "errors": int(row[1] or 0),
        "total_cost_usd": float(row[2] or 0.0),
        "mean_latency_ms": int(round(row[3] or 0)),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_trace.py::TestAggregateRange -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/solo/trace.py tests/test_trace.py
git commit -m "feat(trace): add aggregate_range for eval cost/latency reporting"
```

---

## Task 5: Seed `evals/classify.jsonl` + results dir + gitignore

**Files:**
- Create: `evals/classify.jsonl`
- Create: `evals/results/.gitkeep`
- Modify: `.gitignore`

- [ ] **Step 1: Write the seed JSONL**

`evals/classify.jsonl` (one JSON object per line, no trailing newline issues):

```jsonl
{"raw_text":"explore embeddings for dedup","kind":"idea","priority":"medium"}
{"raw_text":"buy milk on the way home","kind":"hard_task","priority":"high"}
{"raw_text":"figure out positioning for the new feature","kind":"soft_task","priority":"high"}
{"raw_text":"compaction TTL in Claude is 5 minutes","kind":"note","priority":"low"}
{"raw_text":"draft the Q3 review doc by Thursday","kind":"hard_task","priority":"high"}
{"raw_text":"what if we replaced cron with NATS?","kind":"idea","priority":"low"}
{"raw_text":"think through team structure for next half","kind":"soft_task","priority":"medium"}
{"raw_text":"prompt caching paper from Anthropic, worth reading","kind":"note","priority":"low"}
{"raw_text":"book dentist","kind":"hard_task","priority":"medium"}
{"raw_text":"morale on platform team feels off","kind":"soft_task","priority":"high"}
{"raw_text":"could we use Voyage for embeddings?","kind":"idea","priority":"medium"}
{"raw_text":"refile expense reports","kind":"hard_task","priority":"low"}
{"raw_text":"Hofstadter on strange loops","kind":"note","priority":"low"}
{"raw_text":"figure out my mentoring plan","kind":"soft_task","priority":"medium"}
{"raw_text":"interesting that Kimi pricing dropped 30%","kind":"note","priority":"medium"}
```

- [ ] **Step 2: Create the results dir gitkeep**

`evals/results/.gitkeep` — empty file.

- [ ] **Step 3: Add results gitignore**

Append to `.gitignore`:

```
# Eval run outputs are local artifacts, not source.
evals/results/*.json
```

- [ ] **Step 4: Sanity-check the JSONL parses**

Run: `uv run python -c "import json; [json.loads(l) for l in open('evals/classify.jsonl').read().splitlines() if l.strip()]; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add evals/classify.jsonl evals/results/.gitkeep .gitignore
git commit -m "data(evals): seed classify.jsonl with 15 labeled entries"
```

---

## Task 6: `scripts/eval.py` runner

**Files:**
- Create: `scripts/eval.py`

No tests — thin orchestration shell over already-tested units. Hand-tested on first real run.

- [ ] **Step 1: Write the script**

`scripts/eval.py`:

```python
"""Run the classifier against evals/classify.jsonl and report scores.

Usage:
    uv run python scripts/eval.py [--model NAME] [--prompt NAME] [--jsonl PATH] [--db PATH]

Writes a JSON sidecar to evals/results/<UTC-ISO>.json.
"""

import argparse
import asyncio
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from solo.classifier import ClassifyResult
from solo.db import get_connection
from solo.evals import score_kind, score_priority, summarize
from solo.llm import DEFAULT_MODEL, LLMClient
from solo.trace import aggregate_range, ensure_schema


def _max_trace_id(conn) -> int:
    row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM llm_calls").fetchone()
    return int(row[0])


async def _run(model: str, prompt: str, jsonl_path: Path, db_path: Path) -> dict:
    lines = [ln for ln in jsonl_path.read_text().splitlines() if ln.strip()]
    rows_in: list[dict] = []
    for i, ln in enumerate(lines, start=1):
        try:
            rows_in.append(json.loads(ln))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"malformed JSONL at line {i}: {exc}") from exc

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is required")

    # Capture trace id watermark before/after so we aggregate only this run.
    conn = get_connection(str(db_path))
    ensure_schema(conn)
    id_before = _max_trace_id(conn)

    llm = LLMClient(api_key, db_path)

    rows_out: list[dict] = []
    errors: list[dict] = []
    t0 = time.monotonic()
    for r in rows_in:
        try:
            pred: ClassifyResult = await llm.structured(
                prompt,
                ClassifyResult,
                model=model,
                vars={"entry_text": r["raw_text"]},
            )
        except Exception as exc:
            errors.append({"raw_text": r["raw_text"], "error": str(exc)})
            continue
        kind_correct = score_kind(pred.kind, r["kind"])
        priority_correct, priority_distance = score_priority(pred.priority, r["priority"])
        rows_out.append({
            "raw_text": r["raw_text"],
            "actual_kind": r["kind"],
            "predicted_kind": pred.kind,
            "kind_correct": kind_correct,
            "actual_priority": r["priority"],
            "predicted_priority": pred.priority,
            "priority_correct": priority_correct,
            "priority_distance": priority_distance,
            "predicted_summary": pred.summary,
        })
    elapsed = time.monotonic() - t0

    id_after = _max_trace_id(conn)
    trace_agg = aggregate_range(conn, id_min=id_before + 1, id_max=id_after) \
        if id_after > id_before else {"count": 0, "errors": 0,
                                       "total_cost_usd": 0.0, "mean_latency_ms": 0}
    conn.close()

    return {
        "model": model,
        "prompt": prompt,
        "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "elapsed_s": round(elapsed, 2),
        "aggregate": summarize(rows_out),
        "rows": rows_out,
        "errors": errors,
        "trace": trace_agg,
    }


def _print_table(report: dict) -> None:
    agg = report["aggregate"]
    trace = report["trace"]
    n = agg["total"]

    print()
    print(
        f"Eval: {report['model']}  ·  {report['prompt']}  ·  {report['ts']}  ·  "
        f"{n} rows  ·  {report['elapsed_s']}s"
    )
    print()

    def pct(x: float) -> str:
        return f"{x * 100:.1f}%"

    print(
        f"Kind:      {round(agg['kind_accuracy'] * n)}/{n} = {pct(agg['kind_accuracy'])}"
    )
    print(
        f"Priority:  {round(agg['priority_accuracy'] * n)}/{n} = {pct(agg['priority_accuracy'])}   "
        f"off-by-one: {pct(agg['priority_off_by_one'])}   "
        f"off-by-two: {pct(agg['priority_off_by_two'])}"
    )
    print(
        f"Cost:      ${trace['total_cost_usd']:.4f}   "
        f"Mean latency: {trace['mean_latency_ms']}ms"
    )

    if report["errors"]:
        print(f"Errors:    {len(report['errors'])}/{n + len(report['errors'])}")

    if agg["confusion"]:
        kinds = ("idea", "soft_task", "hard_task", "note")
        print()
        print("Confusion (rows = actual, cols = predicted):")
        header = "                " + "  ".join(f"{k[:5]:>5}" for k in kinds)
        print(header)
        for actual in kinds:
            row = "  ".join(
                f"{agg['confusion'][actual][p]:>5}" for p in kinds
            )
            print(f"  {actual:<12}  {row}")


def main() -> None:
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--prompt", default="classifier")
    p.add_argument("--jsonl", default="evals/classify.jsonl")
    p.add_argument("--db", default="./data/solo.db")
    args = p.parse_args()

    report = asyncio.run(
        _run(args.model, args.prompt, Path(args.jsonl), Path(args.db))
    )
    _print_table(report)

    out_dir = Path("evals/results")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{report['ts'].replace(':', '')}.json"
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Confirm the script imports cleanly**

Run: `uv run python -c "import scripts.eval" 2>&1 | tail -5`
Expected: no error (Python imports succeed; the script doesn't run because `main()` is guarded by `__name__`).

If `scripts` isn't an importable package (no `__init__.py`), this is fine — the alternative check is just verifying the file parses:

Run: `uv run python -c "import ast; ast.parse(open('scripts/eval.py').read())" && echo OK`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add scripts/eval.py
git commit -m "feat(eval): add scripts/eval.py runner"
```

---

## Task 7: ADR-0006 — skip auto-grading summary

**Files:**
- Create: `docs/decisions/0006-skip-summary-auto-grading.md`
- Modify: `docs/decisions/README.md`

- [ ] **Step 1: Write the ADR**

`docs/decisions/0006-skip-summary-auto-grading.md`:

```markdown
# 0006 — Skip auto-grading the classifier `summary` field in evals

**Status:** accepted
**Date:** 2026-05-23

## Context

The classifier produces three fields per entry: `kind`, `priority`, `summary`. The first two are categorical and easy to grade against a labeled set. `summary` is free text — one short line capturing the essence of the input. Grading prose is fundamentally different from grading categories.

Three options for grading summary text:

1. **Skip auto-grading; surface predicted summaries in the JSON sidecar for human spot-check.** Cheapest. Schema already enforces non-empty + ≤120 chars.
2. **Character or word-overlap heuristic (Jaccard, BLEU).** Cheap but noisy — a perfectly correct rephrasing scores low.
3. **Embedding-based cosine similarity.** Captures semantic match but requires an embedding pipeline (Voyage API or `sentence-transformers`) we don't have yet — that's slice 6+ territory per `docs/architecture.md` §10.

## Decision

Option 1 for V0. Don't auto-grade summary. Predictions are recorded in the JSON sidecar; a human can scan them in seconds to catch obvious regressions.

## Consequences

**Easier:**
- No false signal from naive overlap metrics.
- No new dependency (embeddings) until we actually need it for dedup.
- Eval runtime stays predictable — one LLM call per row, no embedding round-trip.

**Harder:**
- Summary regressions could ship without being caught by a number.
- The eval table presents only kind+priority scores; "is this prompt better at summarising?" remains a vibes call until we have embeddings.

## Alternatives considered

- **Word-overlap (Jaccard, ROUGE-L)** — rejected; noisy enough that a stylistic rephrase looks like a regression. False signal is worse than no signal here.
- **Embedding cosine** — rejected for now; revisit when slice 6 (dedup) introduces an embedding pipeline. At that point both consumers (dedup + eval) share the same Voyage/local-model dependency.
```

- [ ] **Step 2: Append the index entry**

In `docs/decisions/README.md`, append to the Index list:

```markdown
- [0006 — Skip auto-grading the classifier `summary` field in evals](0006-skip-summary-auto-grading.md)
```

- [ ] **Step 3: Commit**

```bash
git add docs/decisions/0006-skip-summary-auto-grading.md docs/decisions/README.md
git commit -m "docs(decisions): ADR-0006 skip auto-grading summary text"
```

---

## Task 8: Concept primer — `docs/concepts/evaluating-llm-outputs.md`

**Files:**
- Create: `docs/concepts/evaluating-llm-outputs.md`
- Modify: `docs/concepts/README.md` (if it exists with an index)

- [ ] **Step 1: Check the concepts README shape**

Run: `head -30 docs/concepts/README.md`

If it has an Index/list, plan to append. If it's just guidance, no update needed.

- [ ] **Step 2: Write the primer**

`docs/concepts/evaluating-llm-outputs.md`:

```markdown
# Evaluating LLM outputs

## What problem this solves

Prompts drift. Models change. "Did this edit make the classifier better or worse?" is a question that, without a metric, can only be answered by reading outputs and squinting — which doesn't scale and isn't trustworthy. An eval harness turns that question into a number.

## The core idea

Take a small set of inputs where you know the right answer (a *labeled corpus*). Run the model. Compare predictions against labels. Aggregate into a score. That score becomes the unit of "did my change help?"

The tricky part is choosing what to measure. Categorical fields (`kind`: idea/soft_task/hard_task/note; `priority`: low/medium/high) grade cleanly via exact-match accuracy. Free text (`summary`) does not — a perfectly correct rephrasing looks "different" to any string-comparison heuristic. Grading prose well requires either embeddings (compare meanings, not characters) or human judgment.

solo's V0 eval grades the two categorical fields and *surfaces* the summary predictions for a human to scan. We accept that summary regressions aren't caught by a number until we add embeddings (see [ADR-0006](../decisions/0006-skip-summary-auto-grading.md)).

## How solo uses it

- `evals/classify.jsonl` — the labeled corpus. 15 hand-crafted thought-fragments with `kind` and `priority` labels.
- `scripts/eval.py` — sequential runner. Reads JSONL, calls `LLMClient.structured`, scores each row, prints a terminal table and writes `evals/results/<timestamp>.json`.
- `src/solo/evals.py` — pure scoring functions: `score_kind`, `score_priority`, `build_confusion`, `summarize`.
- The metrics reported are: kind accuracy, kind confusion matrix, priority exact-match, priority off-by-one rate, total cost, and mean latency.

The JSON sidecar matters as much as the terminal table — it lets two runs be mechanically diffed. "I changed the prompt and accuracy went 87% → 93%" is a real claim only if you have both reports to compare.

## Common gotchas

- **Tiny corpus = noisy signal.** A 15-entry set tells you about gross misbehavior, not subtle drift. Real prompt iteration needs at least ~100 labeled examples.
- **Labels aren't ground truth — they're *your* truth.** Two reasonable annotators can disagree on whether "what if we replaced cron with NATS?" is an `idea` or a `soft_task`. The eval measures consistency with your taste, not objective correctness.
- **Self-referential prompts pollute results.** If the prompt's examples come from the eval set, you're testing memorization, not generalization. Keep them separate.
- **Cost compounds.** Every eval run is N LLM calls. With sequential runs and a 100-row corpus, even cheap models like MiniMax are non-trivial. The trace table aggregation surfaces this every run.

## Further reading

- [Eugene Yan — Evals](https://eugeneyan.com/writing/evals/) — the practical "how to think about evals" piece.
- [Anthropic docs — Evaluating Claude](https://docs.anthropic.com/en/docs/test-and-evaluate/develop-tests) — Anthropic's framing of the same problem.
- ADR-0006 in this repo for the design choice on summary scoring.
```

- [ ] **Step 3: If `docs/concepts/README.md` has an index, append the entry**

If the README contains a list of primers, add:

```markdown
- [Evaluating LLM outputs](evaluating-llm-outputs.md) — eval harnesses, classifier metrics, why prose is hard to grade
```

(Skip this step if no such index exists.)

- [ ] **Step 4: Commit**

```bash
git add docs/concepts/evaluating-llm-outputs.md docs/concepts/README.md
git commit -m "docs(concepts): primer on evaluating LLM outputs"
```

If `README.md` wasn't modified, omit it from `git add`.

---

## Task 9: HTML walkthrough + status.md

**Files:**
- Modify: `docs/walkthrough.html`
- Modify: `docs/status.md`

- [ ] **Step 1: Update walkthrough.html**

In `docs/walkthrough.html`, make the following changes:

1. Nav-bar slice-5 line: replace `<span class="pill amber">next</span>` with `<span class="pill green">done</span>`.
2. Top meta pills: change `slices 1–4 shipped` → `slices 1–5 shipped`; change `slice 5 queued (eval harness)` → `V0 complete — V1 surface next`.
3. Slice-5 card (`<div class="slice s4">` for the amber/next-styled card): change to `<div class="slice s3">`, replace the body with the shipped shape (see snippet below), flip the `pill amber` to `pill green` and replace "next" with "done".
4. Abstractions grid: add a `solo.evals` card.
5. Concept primers grid: add a card linking to `concepts/evaluating-llm-outputs.md`.
6. ADRs grid: add a card for ADR-0006.
7. Status section bullets: flip slice 5 from "next" to "done"; add a "V1 — `/expand` (hand-rolled agent loop) is next" line, marked queued/muted.
8. Bump "Last regen" date to today.
9. Legend in sidebar: change the slice 5 "next" line; add a new "V1 — next" line if useful (or just remove the slice 5 amber line since nothing in V0 is amber anymore).

Slice-5 card body replacement:

```html
<div class="slice s3">
  <h3>Make classifier quality measurable <span class="pill green">done</span></h3>
  <div class="why">Goal: turn "is this prompt better" from vibes into a number.</div>
  <p>Three pieces:</p>
  <ul>
    <li><strong><code>evals/classify.jsonl</code></strong> — 15 hand-labeled thought-fragments. Mix of clear-cut and intentionally ambiguous entries (e.g. <code>"what if we replaced cron with NATS?"</code>).</li>
    <li><strong><code>scripts/eval.py</code></strong> — sequential runner. Reads JSONL, calls <code>LLMClient.structured</code>, scores, prints a terminal table, writes a JSON sidecar to <code>evals/results/&lt;UTC-ISO&gt;.json</code> for mechanical diffs.</li>
    <li><strong><code>src/solo/evals.py</code></strong> — pure scorers: <code>score_kind</code>, <code>score_priority</code> (exact + off-by-one), <code>build_confusion</code>, <code>summarize</code>.</li>
  </ul>
  <p>Cost &amp; latency for each run come from the <code>llm_calls</code> trace table via <code>trace.aggregate_range</code> — eval rows count toward the cost roll-up just like production calls.</p>
  <p>Summary text is <em>not</em> auto-graded — see <a href="decisions/0006-skip-summary-auto-grading.md">ADR-0006</a>. Spec at <a href="superpowers/specs/2026-05-23-eval-harness-design.md">specs/2026-05-23-eval-harness-design.md</a>.</p>
</div>
```

- [ ] **Step 2: Update status.md**

Rewrite the body so:

- `Last updated` = `2026-05-23 — by Claude Code (Opus 4.7)`.
- `Current state` reflects V0 fully done: capture, classifier, /top3 + /log, eval harness all shipped. Note that with slice 5 done, V0 is complete.
- `Done in slice 5` lists: `src/solo/evals.py`, `scripts/eval.py`, `evals/classify.jsonl`, `solo.trace.aggregate_range`, ADR-0006, concept primer.
- `What's next` numbered list: marks slice 5 done; the next item is **V1 entry — `/expand` (hand-rolled agent loop)** per `docs/architecture.md` §1.
- `Pending manual verification` still lists the live classifier test and the Telegram smoke test, and adds: a real eval run against OpenRouter to confirm the harness produces sane numbers.

- [ ] **Step 3: Sanity-check the walkthrough renders**

Run: `open docs/walkthrough.html`
Expected: slice 5 card now green; new abstraction/concept/ADR cards present; status section shows V0 complete.

- [ ] **Step 4: Commit**

```bash
git add docs/walkthrough.html docs/status.md
git commit -m "docs: flip slice 5 to done; mark V0 complete in status + walkthrough"
```

---

## Task 10: Verification cycle + push

**Files:** none

- [ ] **Step 1: Full test suite**

Run: `uv run pytest -v 2>&1 | tail -10`
Expected: all green (slice-4 count + new slice-5 tests; 2 live tests skipped without API key).

- [ ] **Step 2: Lint**

Run: `uv run ruff check .`
Expected: clean.

- [ ] **Step 3: Format check on slice-5 files**

Run:
```bash
uv run ruff format --check src/solo/evals.py scripts/eval.py tests/test_evals.py
```

If diff exists: `uv run ruff format src/solo/evals.py scripts/eval.py tests/test_evals.py` and commit as a `style:` commit.

- [ ] **Step 4: Push**

Run: `git push origin main`
Expected: clean push.

- [ ] **Step 5: Run both reviewers on the slice-5 diff**

`solo-reviewer` agent + generic code-reviewer agent on the commit range from before slice 5 began through HEAD. Address any blockers; re-run pytest after fixes; re-push.

---

## Spec coverage check

| Spec section | Tasks |
|---|---|
| §3 — `solo.evals` module | Tasks 1, 2, 3 |
| §3 — `scripts/eval.py` | Task 6 |
| §3 — JSONL seed | Task 5 |
| §3 — `evals/results/.gitkeep` + gitignore | Task 5 |
| §4 — metrics (kind, priority) | Tasks 1, 3 |
| §5 — output (terminal + JSON sidecar) | Task 6 |
| §6 — cost/latency aggregation from `llm_calls` | Task 4 |
| §7 — error handling (per-row continue; malformed JSONL abort; missing key abort) | Task 6 |
| §8 — test plan | Tasks 1, 2, 3 |
| §9 — concept primer | Task 8 |
| §9 — ADR-0006 | Task 7 |
| §9 — walkthrough update | Task 9 |
| §9 — status.md update | Task 9 |

No gaps.
