# Slice 5 — Classifier eval harness design

**Date:** 2026-05-23
**Status:** approved, ready for implementation
**Author:** Claude Code (Opus 4.7), driven by kb

## 1. Purpose

Slice 3 shipped a classifier; slice 4 surfaced its output. Neither has a metric. Today the only way to evaluate a prompt change is to read a few outputs and squint. That's vibes, not engineering.

Slice 5 turns "is this prompt better" into a number. A small hand-labeled corpus (`evals/classify.jsonl`) + a runner script (`scripts/eval.py`) measure per-call accuracy across `kind` and `priority`, with the full per-row trace dumped to a JSON sidecar for mechanical diffs across runs.

Per `AGENTS.md` V0 scope item 6.

## 2. Resolved design questions

| # | Question | Resolution | Rationale |
|---|---|---|---|
| D1 | Who writes the labels? | **Claude seeds ~15 synthetic examples** | Fastest to ship; the harness is the asset, the data grows over time. kb can replace synthetic examples with real entries by editing the JSONL. |
| D2 | Priority metric? | **Exact-match accuracy + off-by-one rate** | Captures "mostly right"; cheap to compute; easy to read. Mean ordinal distance is harder to interpret at a glance. |
| D3 | Output format? | **Terminal table + JSON sidecar** | Pretty output for the human running it; JSON for two-run diffs. Best of both. |
| D4 | Score the summary text? | **No — surface predictions only** | Auto-grading prose with prose needs embeddings (slice 6+ territory). Schema already enforces length/non-empty. Captured in ADR-0006. |
| D5 | Concurrency? | **Sequential** | 15 calls × ~3s = under a minute. Parallel via `asyncio.gather` is a YAGNI optimization. |
| D6 | Where does the eval logic live? | **`src/solo/evals.py` for pure scoring + `scripts/eval.py` as thin CLI** | Pure functions are unit-testable without network; the script is a wiring shell. |

## 3. Module shape

```
src/solo/
  evals.py            # NEW — pure scoring + summarize()
scripts/
  eval.py             # NEW — CLI entry; loads JSONL, runs LLMClient, summarizes
evals/
  classify.jsonl      # NEW — 15 seed records
  results/
    .gitkeep          # NEW — output dir; results gitignored
tests/
  test_evals.py       # NEW
.gitignore            # MOD — ignore evals/results/*.json
```

### `solo.evals`

Pure functions only. Zero IO, zero LLM. Testable as a unit.

```python
from typing import Literal

Kind = Literal["idea", "soft_task", "hard_task", "note"]
Priority = Literal["low", "medium", "high"]

_PRIORITY_ORDER = {"low": 0, "medium": 1, "high": 2}


def score_kind(predicted: Kind, actual: Kind) -> bool:
    return predicted == actual


def score_priority(predicted: Priority, actual: Priority) -> tuple[bool, int]:
    """Returns (exact_match, ordinal_distance). Distance is |pred - actual|."""
    distance = abs(_PRIORITY_ORDER[predicted] - _PRIORITY_ORDER[actual])
    return distance == 0, distance


def build_confusion(rows: list[dict]) -> dict[str, dict[str, int]]:
    """Build a confusion matrix keyed by [actual_kind][predicted_kind] -> count."""
    kinds = ("idea", "soft_task", "hard_task", "note")
    matrix = {a: {p: 0 for p in kinds} for a in kinds}
    for row in rows:
        matrix[row["actual_kind"]][row["predicted_kind"]] += 1
    return matrix


def summarize(rows: list[dict]) -> dict:
    """Aggregate per-row results into a summary dict. Pure; no rendering."""
    total = len(rows)
    if total == 0:
        return {"total": 0, "kind_accuracy": 0.0, "priority_accuracy": 0.0,
                "priority_off_by_one": 0.0, "confusion": {}}
    kind_correct = sum(1 for r in rows if r["kind_correct"])
    p_exact     = sum(1 for r in rows if r["priority_distance"] == 0)
    p_off_by_1  = sum(1 for r in rows if r["priority_distance"] == 1)
    p_off_by_2  = sum(1 for r in rows if r["priority_distance"] == 2)
    return {
        "total": total,
        "kind_accuracy": kind_correct / total,
        "priority_accuracy": p_exact / total,
        "priority_off_by_one": p_off_by_1 / total,
        "priority_off_by_two": p_off_by_2 / total,
        "confusion": build_confusion(rows),
    }
```

### `scripts/eval.py`

Thin wiring. Loads JSONL, opens `LLMClient`, runs sequentially, prints + dumps.

```python
import argparse
import asyncio
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from solo.classifier import ClassifyResult
from solo.evals import score_kind, score_priority, summarize
from solo.llm import DEFAULT_MODEL, LLMClient


async def _run(model: str, prompt: str, jsonl_path: Path, db_path: Path) -> dict:
    rows_in = [json.loads(line) for line in jsonl_path.read_text().splitlines() if line.strip()]
    llm = LLMClient(os.environ["OPENROUTER_API_KEY"], db_path)
    rows_out: list[dict] = []
    t0 = time.monotonic()
    for r in rows_in:
        pred: ClassifyResult = await llm.structured(
            prompt, ClassifyResult, model=model,
            vars={"entry_text": r["raw_text"]},
        )
        kind_correct = score_kind(pred.kind, r["kind"])
        p_correct, p_distance = score_priority(pred.priority, r["priority"])
        rows_out.append({
            "raw_text": r["raw_text"],
            "actual_kind": r["kind"],
            "predicted_kind": pred.kind,
            "kind_correct": kind_correct,
            "actual_priority": r["priority"],
            "predicted_priority": pred.priority,
            "priority_correct": p_correct,
            "priority_distance": p_distance,
            "predicted_summary": pred.summary,
        })
    elapsed = time.monotonic() - t0
    agg = summarize(rows_out)
    return {
        "model": model, "prompt": prompt,
        "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "elapsed_s": round(elapsed, 2),
        "aggregate": agg, "rows": rows_out,
    }


def _print_table(report: dict) -> None:
    ...  # pretty terminal output


def main() -> None:
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--model",  default=DEFAULT_MODEL)
    p.add_argument("--prompt", default="classifier")
    p.add_argument("--jsonl",  default="evals/classify.jsonl")
    p.add_argument("--db",     default="./data/solo.db")
    args = p.parse_args()

    report = asyncio.run(_run(args.model, args.prompt,
                              Path(args.jsonl), Path(args.db)))
    _print_table(report)
    out_dir = Path("evals/results")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{report['ts'].replace(':', '')}.json"
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\nWrote {out_path}")
```

### `evals/classify.jsonl` seed (sketch — full set in implementation)

```
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

15 records covering all 4 kinds × varied priorities, with a few intentional edges:
- "what if we replaced cron with NATS?" — idea-or-soft_task ambiguity.
- "figure out positioning" vs "figure out my mentoring plan" — both soft_task but priority varies.
- "compaction TTL" vs "interesting that Kimi pricing dropped" — both notes but priority varies.

## 4. Metrics in detail

| Metric | Definition |
|---|---|
| **Kind accuracy** | exact-match `predicted_kind == actual_kind`. Reported as percentage + per-class precision via confusion matrix. |
| **Priority accuracy (exact)** | `predicted_priority == actual_priority`. |
| **Priority off-by-one rate** | `\|pred - actual\| == 1` on the ordinal `low<medium<high`. |
| **Priority off-by-two rate** | `\|pred - actual\| == 2`. Should be near zero on any working prompt. |
| **Summary** | NOT scored. Predictions surfaced in JSON sidecar for spot-checking. See ADR-0006. |
| **Cost / latency** | Aggregated from the `llm_calls` trace table for the eval timestamp window. Reported in the terminal table. |

## 5. Output

### Terminal

```
Eval: minimax/minimax-m2.7  ·  classifier  ·  2026-05-23T22:14:00Z  ·  15 rows  ·  28.3s

Kind:      14/15 = 93.3%
Priority:  11/15 = 73.3%   off-by-one: 4/15 = 26.7%   off-by-two: 0/15
Cost:      $0.0042         Mean latency: 1.84s

Confusion (rows = actual, cols = predicted):
                idea  soft  hard  note
       idea       4     1     0     0
       soft_task  0     3     0     0
       hard_task  0     0     4     0
       note       0     0     0     3

Wrote evals/results/2026-05-23T221400Z.json
```

### JSON sidecar

Path: `evals/results/<YYYYMMDDTHHMMSSZ>.json`. Includes the full `report` dict from `_run`: top-level metadata, the aggregate block, and the per-row trace (raw_text, actual + predicted kind/priority, scoring flags, predicted summary).

`evals/results/` is gitignored — results are local artifacts, not source.

## 6. Cost & latency aggregation

The terminal table reports cost/latency derived from `llm_calls` rows written during the eval run. Two ways to do this:

- **Naive:** read the latest N rows from `llm_calls` after the run completes (where N = eval row count). Simple, mostly correct.
- **Robust:** capture `min(id)` before the run and `max(id)` after; aggregate within that range.

Going with **robust** because the bot might be running concurrently and writing trace rows for unrelated `/top3` calls.

## 7. Error handling

| Failure | Behavior |
|---|---|
| `LLMClient.structured` raises (one row) | Print a row-level error, continue. Don't tank the whole eval for one bad call. Tally errors separately; report at the bottom. |
| `evals/classify.jsonl` malformed | Print line number, abort. Eval data integrity matters. |
| `OPENROUTER_API_KEY` missing | Fail fast at boot. |

## 8. Test plan

`tests/test_evals.py` — pure scoring tests only. No live LLM, no script-level integration. The CLI shell is thin enough that hand-testing on first run is sufficient.

- `test_score_kind_match` / `test_score_kind_mismatch`
- `test_score_priority_exact_returns_distance_zero`
- `test_score_priority_off_by_one`
- `test_score_priority_off_by_two`
- `test_build_confusion_shape_and_counts`
- `test_summarize_empty_returns_zeros`
- `test_summarize_computes_rates`
- `test_summarize_includes_confusion`

## 9. Doc artifacts

- `docs/concepts/evaluating-llm-outputs.md` — new primer (300–500 words). Covers: why grade prompts numerically, kind vs priority metrics, why we don't score summary, the cost of "ground truth."
- `docs/decisions/0006-skip-summary-auto-grading.md` — records D4.
- `docs/walkthrough.html` — add slice 5 card; flip status sections; add `solo.evals` to abstractions; add ADR-0006 card; add concept primer card.
- `docs/status.md` — slice 5 done; "what's next" = first V1 surface (likely `/expand`).

## 10. Out of scope

- Parallel eval execution.
- Embedding-based summary scoring.
- CI gating on accuracy thresholds.
- Multi-prompt A/B in one run — run twice with different `--prompt` and diff JSON.
- Multi-model A/B in one run — same as above with `--model`.
- Web UI for eval results — not needed; the terminal table + JSON diff covers it.
