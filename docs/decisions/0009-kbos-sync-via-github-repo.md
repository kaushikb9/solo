# 0009 — kbOS sync goes through a GitHub repo, not an API

**Status:** accepted
**Date:** 2026-06-11

## Context

solo's role narrowed (2026-06-11): it is the low-friction capture + morning-feedback
surface; kbOS (markdown brain on the laptop) is the primary system. kbOS needs to read
solo's pending tasks at session start; solo needs to deliver a kbOS-authored briefing
each morning. Three ways to connect a Railway-hosted bot to a laptop-local markdown repo:

1. **Shared private GitHub repo as a message bus.** solo pushes `from-solo/tasks.md`
   via the contents API; kbOS pulls at session start and pushes `to-solo/briefing.md`
   at session end; solo's daily job fetches and sends it to Telegram.
2. **HTTP API on solo.** kbOS calls Railway. Requires auth design, uptime coupling,
   and code on both sides — kbOS is constitutionally no-code.
3. **Direct DB access** (litestream/Turso/Railway CLI). Couples kbOS to solo's schema
   and hosting; fragile.

The owner's explicit constraint: "build once and never worry about it." He rejected
OpenClaw/Hermes-style runtimes because they induced tinkering loops.

## Decision

Shape 1. Two markdown files in a dedicated private repo (`kb-sync`), GitHub contents
API, snapshot pushed only on content change (5-min repeating job), briefing delivered
by a `run_daily` job. Sync is fully optional: unset env vars → solo behaves exactly
as before. Errors are logged and swallowed — sync can never take the bot down.

## Consequences

**Easier:**
- Zero new infrastructure; GitHub is the queue, the auth, and the audit log.
- kbOS side is pure instructions (git pull / read / write / git push).
- Full snapshot (not a delta stream) makes the reader stateless — no dedup logic.
- Either side can be down for days; the bus holds the latest state.

**Harder:**
- Sync latency is minutes (snapshot) to a day (briefing), not real-time. Acceptable:
  the briefing is daily by design and kbOS sessions are explicit.
- A mid-job race (two writers on one file) is theoretically possible but the writers
  own disjoint files, so in practice it can't happen.
- Railway holds a GitHub PAT. Mitigated: fine-grained, scoped to kb-sync only —
  never to the kbOS repo (therapy material).

## Alternatives considered

- **HTTP API** — rejected: more code, auth surface, and uptime coupling for no gain
  at this scale.
- **Direct DB replication** — rejected: schema coupling and exactly the kind of
  plumbing that turns into a tinkering loop.
