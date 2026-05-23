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
        rows_out.append(
            {
                "raw_text": r["raw_text"],
                "actual_kind": r["kind"],
                "predicted_kind": pred.kind,
                "kind_correct": kind_correct,
                "actual_priority": r["priority"],
                "predicted_priority": pred.priority,
                "priority_correct": priority_correct,
                "priority_distance": priority_distance,
                "predicted_summary": pred.summary,
            }
        )
    elapsed = time.monotonic() - t0

    id_after = _max_trace_id(conn)
    if id_after > id_before:
        trace_agg = aggregate_range(conn, id_min=id_before + 1, id_max=id_after)
    else:
        trace_agg = {
            "count": 0,
            "errors": 0,
            "total_cost_usd": 0.0,
            "mean_latency_ms": 0,
        }
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

    if n > 0:
        kind_hits = round(agg["kind_accuracy"] * n)
        priority_hits = round(agg["priority_accuracy"] * n)
        print(f"Kind:      {kind_hits}/{n} = {pct(agg['kind_accuracy'])}")
        print(
            f"Priority:  {priority_hits}/{n} = {pct(agg['priority_accuracy'])}   "
            f"off-by-one: {pct(agg['priority_off_by_one'])}   "
            f"off-by-two: {pct(agg['priority_off_by_two'])}"
        )

    print(f"Cost:      ${trace['total_cost_usd']:.4f}   Mean latency: {trace['mean_latency_ms']}ms")

    if report["errors"]:
        print(f"Errors:    {len(report['errors'])} (of {n + len(report['errors'])} attempted)")

    if agg["confusion"]:
        kinds = ("idea", "soft_task", "hard_task", "note")
        print()
        print("Confusion (rows = actual, cols = predicted):")
        header = " " * 16 + "  ".join(f"{k[:5]:>5}" for k in kinds)
        print(header)
        for actual in kinds:
            cells = "  ".join(f"{agg['confusion'][actual][p]:>5}" for p in kinds)
            print(f"  {actual:<12}  {cells}")


def main() -> None:
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--prompt", default="classifier")
    p.add_argument("--jsonl", default="evals/classify.jsonl")
    p.add_argument("--db", default="./data/solo.db")
    args = p.parse_args()

    report = asyncio.run(_run(args.model, args.prompt, Path(args.jsonl), Path(args.db)))
    _print_table(report)

    out_dir = Path("evals/results")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{report['ts'].replace(':', '')}.json"
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
