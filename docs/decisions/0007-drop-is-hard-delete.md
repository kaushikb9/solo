# 0007 — `/drop` is a hard delete; `/done` is the soft-state half

**Status:** accepted
**Date:** 2026-05-24

## Context

V0.1 introduces mutation commands. Two reasonable shapes for "remove from active view":

1. **Hard delete on `/drop`; soft `done` flag on `/done`.** Two states the user explicitly chooses between. Smaller schema (one boolean).
2. **Soft `status` column with values `active | done | dropped`.** Symmetric three-state lifecycle; misclicks recoverable.

## Decision

Shape 1. `/drop` is a hard `DELETE FROM entries`. `/done` sets `done = 1` and the row stays in `/all`.

The user explicitly chose hard delete during brainstorming, after seeing both options laid out.

## Consequences

**Easier:**
- Schema is one boolean (`done`) instead of a three-valued enum.
- The user's mental model is binary: "useful → keep; noise → delete forever."
- `/all` stays focused on "things I actually captured" rather than including a `dropped` graveyard.

**Harder:**
- Misclicks on `/drop` are unrecoverable. There is no `/undrop`.
- Trace rows (`llm_calls`) are independent of `entries`, so cost/eval history survives even when entries don't.
- If the user later wants "things I considered but dropped," they'd need a schema change (and historical data is gone).

## Alternatives considered

- **Soft `status` column** — rejected per D1 in the slice-6 spec. Reconsider if the user starts wanting an `/undrop`.
- **Two-stage drop (`/drop` → "are you sure?" → `/confirm`)** — rejected as Telegram-UX clutter. The user is the only person who can use the bot anyway (allow-list).
