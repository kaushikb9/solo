# 0003 — Store classifier output on `entries`, not a side table

- **Status:** accepted
- **Date:** 2026-05-10

## Context

Slice 3 introduces a classifier producing `(kind, summary, priority)` per entry. Two storage options:

1. Add columns to `entries`: `kind`, `summary`, `priority`, `classification_attempts`.
2. Separate `classifications` table with a foreign key back to `entries`, supporting multiple rows per entry (history of re-classifications, model drift studies, etc.).

V0 has no use case for re-classification history. `/top3` and `/log` (slices 4 and 5) read one classification per entry. The entries are personal, low-volume (~5–30/day), and the classifier output rides alongside the raw text.

## Decision

Add `kind`, `summary`, `priority`, and `classification_attempts` directly as columns on `entries`. Migration is idempotent — runs in `get_connection`. `classify_pending` (`src/solo/classifier.py`) writes via `apply_classification` (`src/solo/db.py`) which sets the columns and flips `classified=1` in the same `UPDATE`.

## Consequences

**Easier:**
- One row read for `/top3` and `/log` — no joins.
- Schema fits the V0 mental model: an entry *is* a classified thought.
- Migration is one `ALTER TABLE` per column; no cross-table backfill.

**Harder:**
- Re-classification overwrites. If we want history (e.g., to compare classifier prompts over time), we'd need a side table or a new `classification_history` log.
- Schema evolution: every new classifier field is another `ALTER TABLE`.

**Revisit when:** we want to keep history of multiple classifier runs over the same entry, or the classifier produces array-shaped output (tags, multi-label).

## Alternatives considered

- **Separate `classifications` table.** Cleaner separation, supports history. Rejected for V0: no consumer of history yet, more joins, more boilerplate. (`docs/superpowers/specs/2026-05-10-classifier-design.md` D4 captures the tradeoff.)
- **JSON column on `entries`.** Schema-flexible. Rejected: loses SQL queryability — `/top3` ranking and `/log` grouping become awkward.
