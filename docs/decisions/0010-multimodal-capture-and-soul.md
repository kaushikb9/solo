# 0010 — solo 2.0: multimodal capture, 7-day media retention, the soul

**Status:** accepted
**Date:** 2026-06-11

## Context

solo's role (post ADR-0009) is the away-from-laptop capture + feedback surface, with
the explicit goal of replacing reminder apps, note apps, outliners, and pen-and-paper.
Text-only capture can't do that. Host disk is limited, and the brain — not solo — is
the permanent home of anything captured. Separately, solo knew nothing about its
user: briefings came from the brain, but `/top` and capture feedback were generic.

## Decision

Three additions, all riding the existing pipeline:

1. **Multimodal capture.** Photos/screenshots → vision model describes/transcribes
   (`describe_image` prompt); voice notes → transcription via a multimodal chat model.
   The derived text becomes `entries.raw_text` with `source` + `media_path` columns —
   so classification, `/top`, snapshots, and sync all work unchanged. A failed model
   call still inserts a placeholder entry; capture is never lost.
2. **7-day retention, sync-gated.** Media binaries are pushed to the sync repo
   (`from-solo/media/entry-<id>-<file>`) by the 5-min flush job; a daily 3am job purges
   local files older than `SOLO_MEDIA_RETENTION_DAYS` — **only if synced**. Unsynced
   media is never deleted, so a sync outage can't destroy captures. The brain collects
   and then deletes media from the bus on its side.
3. **The soul.** The brain authors `to-solo/soul.md` (who the user is, how to coach
   them, current focus). solo fetches it and **persists it to the local `settings`
   table** — the DB on the private volume is the runtime source of truth, surviving
   restarts and network failures. It becomes the system prompt for `/coach`; `/soul`
   shows it raw. solo's codebase contains zero personal information by design: the
   repo is public, the soul travels private-repo → private-DB only.

## Consequences

**Easier:** one capture surface for everything; media has a permanent home (the
brain) and a bounded footprint (the bot host); coach replies reflect the brain's
model of the user without solo's code or repo storing any of it.

**Harder / risks:**
- Audio transcription via OpenRouter `input_audio` with ogg/opus needs live
  verification per provider; model is env-swappable (`SOLO_AUDIO_MODEL`) if the
  default can't take ogg.
- Vision/transcription adds per-capture LLM cost and ~seconds of latency (mitigated:
  instant ack, then edited with the derived text).
- The sync repo grows with media until the brain cleans it; acceptable for one user.

## Alternatives considered

- **Object storage (S3/R2) for media** — rejected: new credential + service for
  personal scale; GitHub contents API already transports files ≤20MB.
- **Whisper/STT API for voice** — deferred: a second API dependency; multimodal chat
  models transcribe well enough and keep everything behind OpenRouter + LLMClient
  (one trace path).
- **HTTP endpoint for updating the soul** — rejected: the bot is a long-polling
  process with no web server; adding one means auth, TLS, and attack surface for a
  single user. The GitHub contents API on the private sync repo *is* the
  authenticated update endpoint; solo persists the result to its DB.
- **Soul baked into solo's repo** — rejected twice over: personality must evolve
  without deploys, and the repo is public — personal data never enters the codebase.
