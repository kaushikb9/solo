# 0008 — `@name` extraction is a regex at insert time, not an LLM-inferred field

**Status:** accepted
**Date:** 2026-05-24

## Context

V0.1 surfaces a `👥 @name` marker in `/top3` and `/list`. Three ways to source the data:

1. **LLM-inferred field on `ClassifyResult`** — add `source: self | external` or similar; the model reads context and tags. Magical, requires schema bump on entries + prompt update + eval relabeling.
2. **Regex at insert time** — extract `@\w+` from `raw_text`, store as CSV in a `mentions` column.
3. **Hybrid** — regex for the @name path, LLM-inferred for the "external request without a name" path.

## Decision

Shape 2 only. `solo.mentions.extract` runs at `insert_entry` time and writes a CSV to `mentions`. The classifier is unchanged. No LLM cost added.

The LLM-inferred external-ask slot (rendered as 🔔) is **reserved visually** in the format but not implemented in this slice. Re-litigate if nameless asks become a real pattern.

## Consequences

**Easier:**
- Zero new LLM cost; zero classifier prompt churn; zero eval relabeling.
- Deterministic and instant — the marker appears on the row immediately, before the classifier has run.
- The data path is independent of the classifier: a row with no kind/summary still has the right marker.

**Harder:**
- Entries that imply a person without explicitly @-naming them (e.g. "boss wants the deck by Friday") get the default 💡 marker. The user has to type `@boss` themselves to surface the marker.
- Convention drift: if the user starts using `#tag` or `+person`, this slice silently ignores it.
- Existing rows (captured before this slice) have NULL `mentions` — they render as 💡 forever unless re-inserted.

## Alternatives considered

- **LLM-inferred `source` field** — rejected for V0.1; deferred. Reconsider after a week of real use shows whether nameless asks are common enough to justify the cost.
- **Hybrid** — rejected; adds complexity now for unclear payoff. Easier to add the LLM path later on top of the regex path than the reverse.
