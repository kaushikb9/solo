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
- Cost and latency per run come from the `llm_calls` trace table via `solo.trace.aggregate_range(conn, id_min, id_max)` — the runner snapshots the max id before the run and after, then aggregates only within that range.

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
