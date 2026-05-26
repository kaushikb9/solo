# Prod → local DB sync design

**Date:** 2026-05-26
**Status:** approved, ready for implementation
**Author:** Claude Code (Opus 4.7), driven by kb

## 1. Purpose

Local dev should always exercise real data. Today `data/solo.db` on the laptop drifts from the Railway-hosted prod DB the moment kb captures a thought via Telegram. There is no command to refresh local from prod, so kb either tests against stale data or hand-copies the file.

This spec defines a one-shot, on-demand pull: `uv run python scripts/pull_prod_db.py` produces a consistent snapshot of the prod SQLite DB and swaps it into `data/solo.db`, keeping the previous local DB as a timestamped backup.

This is a developer tool. It does not affect runtime behavior of the bot. It is not part of V0 / V0.1 scope; it is operational infrastructure.

## 2. Resolved design questions

| # | Question | Resolution | Rationale |
|---|---|---|---|
| D1 | Cadence — on-demand, pre-run hook, or continuous replication? | **On-demand script** | Simplest. kb wants explicit control. No background processes. |
| D2 | Local DB on pull — overwrite, backup-then-overwrite, or side path? | **Backup then overwrite** | Safety net for the last few local runs without complicating the path the bot reads from. |
| D3 | Access mechanism — Railway CLI, web dashboard, or Litestream? | **`railway ssh` + `sqlite3 .backup`** | CLI is already installed + logged in; no new infra; works on Hobby plan. Litestream rejected as overkill for on-demand. |
| D4 | Direction — one-way or bi-directional? | **One-way (prod → local)** | Prod is canonical. Pushing local → prod risks clobbering captures. Out of scope. |
| D5 | Backup retention | **Last 3** | Reasonable disk guard. Older backups pruned each run. |
| D6 | Integrity check on the downloaded snapshot | **Yes** (`PRAGMA integrity_check`) | Catches corruption from a truncated/garbled transfer before we swap. ~50 ms. |
| D7 | Bot-side `/dump` Telegram command as an alternative? | **Rejected** | Violates "capture must never fail" by adding surface area; sending DB through chat is a security smell. |

## 3. Surface

A single command:

```bash
uv run python scripts/pull_prod_db.py
```

No flags. Exits 0 on success, non-zero on any failure with a clear stderr message. Idempotent — rerun anytime.

On success, prints (to stdout):

```
pulled prod DB → data/solo.db
  entries:   <N>
  llm_calls: <M>
  size:      <bytes formatted>
backup kept at data/solo.db.bak-<YYYYMMDD-HHMMSS>
pruned old backups (kept 3 most recent)
```

## 4. Steps

The script is a linear pipeline. Each step is a function; the orchestration is a `main()` that calls them in order and exits non-zero on the first failure.

1. **Preflight**
   - `railway` is on PATH (`shutil.which("railway")`).
   - `railway status --json` succeeds and reports `project.name == "solo"` and a linked `solo` service.
   - On failure: print the exact `railway` command kb needs to run to fix it, exit non-zero.

2. **Remote snapshot + stream down**
   - Invoke `railway ssh` with a single remote command:
     ```sh
     sqlite3 /app/data/solo.db ".backup /tmp/solo-snap.db" && \
       base64 /tmp/solo-snap.db && \
       rm -f /tmp/solo-snap.db
     ```
   - SQLite's `.backup` API is online and consistent under concurrent writes (WAL-safe).
   - Base64 keeps the binary safe across the websocket-backed `railway ssh` channel.
   - Capture stdout into memory (DB is ~0.1 GB per `railway status`; comfortable for in-memory base64 → bytes).
   - On non-zero exit or empty stdout: bail before touching anything local.

3. **Decode + integrity-check**
   - Decode base64 to bytes; write atomically to `data/solo.snapshot.tmp`.
   - Open with `sqlite3` and run `PRAGMA integrity_check;` — must return exactly `ok`.
   - Confirm the `entries` table exists (`SELECT 1 FROM sqlite_master WHERE type='table' AND name='entries';`).
   - On failure: delete `data/solo.snapshot.tmp`, leave existing local DB intact, exit non-zero.

4. **Backup current local**
   - If `data/solo.db` exists, move it (and any `data/solo.db-wal`, `data/solo.db-shm` siblings) to `data/solo.db.bak-<YYYYMMDD-HHMMSS>` (UTC). Siblings are moved with the same suffix.
   - After move, list `data/solo.db.bak-*`, sort by timestamp (lexicographic on the suffix is sufficient since the format is fixed-width), and delete all but the 3 most recent. WAL/SHM siblings of pruned backups are pruned with them.

5. **Swap in**
   - `os.rename("data/solo.snapshot.tmp", "data/solo.db")`. Atomic on the same filesystem.

6. **Report**
   - Open `data/solo.db`, count rows in `entries` and `llm_calls`, get file size, print the success block above.

## 5. Invariants

**At every moment, either the old `data/solo.db` is intact, or a verified new one is in place.** Never both gone, never a half-written one.

This is enforced by the ordering: the snapshot is fully downloaded and integrity-checked **before** we touch the local DB; the swap is a single `rename` on the same filesystem.

If the script crashes between steps 4 and 5 (`mv` already moved local DB to a `.bak-…` path, but the snapshot hasn't been renamed yet), recovery is one `mv data/solo.snapshot.tmp data/solo.db`. The script's module docstring documents this.

## 6. Failure modes

| Failure | Behavior | Local DB state |
|---|---|---|
| `railway` missing / not logged in / wrong project | Exit non-zero with fix-it message | unchanged |
| `railway ssh` exits non-zero | Exit non-zero, print stderr | unchanged |
| `railway ssh` returns empty stdout | Exit non-zero | unchanged |
| Base64 decode fails | Delete tmp, exit non-zero | unchanged |
| Integrity check fails | Delete tmp, exit non-zero | unchanged |
| Disk full mid-stream | Decode fails or tmp write errors; delete tmp, exit non-zero | unchanged |
| Crash between bak-rename and snapshot-rename | Tmp + bak both exist; doc explains one-line recovery | recoverable |

## 7. Code shape

- **File:** `scripts/pull_prod_db.py`
- **Deps:** Python stdlib only (`subprocess`, `pathlib`, `base64`, `sqlite3`, `shutil`, `datetime`, `sys`, `json`).
- **Public functions:**
  - `preflight() -> None` — raises a `PullError` with a fix-it message on any precondition fail.
  - `fetch_snapshot() -> bytes` — runs `railway ssh`, decodes base64, returns DB bytes.
  - `verify_snapshot(path: Path) -> None` — opens the snapshot, runs `PRAGMA integrity_check`, confirms `entries` table.
  - `rotate_backups(data_dir: Path, keep: int = 3) -> list[Path]` — moves current `solo.db` (+ siblings) to a timestamped path and prunes older. Pure-ish (filesystem side effects but deterministic given inputs); easy to unit-test.
  - `swap_in(snapshot_tmp: Path, target: Path) -> None` — atomic rename.
  - `report(db_path: Path, backup: Path | None) -> None` — prints the success block.
  - `main() -> int` — orchestration, returns exit code.
- **Custom exception:** `class PullError(Exception)` — caught only in `main()` to convert to a clean non-zero exit + stderr message. Anywhere else, raise it.
- **No LLM calls.** No `LLMClient` involvement. No `llm_calls` rows written.
- **No changes to `src/solo/`.**

## 8. Tests

- **Unit (`tests/test_pull_prod_db.py`)**
  - `rotate_backups` with 0, 1, 3, 5 existing backups → asserts correct files retained, correct pruning. Uses `tmp_path`.
  - `rotate_backups` correctly handles `-wal`/`-shm` siblings (moves them with the same suffix; prunes them with their parent).
  - `verify_snapshot` against a known-good fixture SQLite file → passes.
  - `verify_snapshot` against a truncated file → raises `PullError`.
  - `verify_snapshot` against a valid SQLite file *without* an `entries` table → raises `PullError`.
- **Live smoke (manual, before claiming done — per AGENTS.md verification cycle)**
  - Run script once with Railway linked. Verify:
    - `entries` row count matches `/all` output in Telegram.
    - `data/solo.db.bak-<ts>` exists.
    - Bot starts cleanly against the pulled DB.
  - Run script three more times. Verify retention prunes to 3 backups.

## 9. Documentation rituals

- **No concept primer needed.** This change introduces no new AI/agent concept — it's pure ops.
- **ADR-0009** — `docs/decisions/0009-prod-db-sync.md` — record the choice of `railway ssh` + `.backup` over Litestream / bot-side dump. ~250 words; the decision is non-trivial enough to deserve a short note.
- **`AGENTS.md`** — add `uv run python scripts/pull_prod_db.py  # pull prod DB to local` under "Common commands".
- **`docs/status.md`** — add a line under the slice 6 manifest noting the new dev tool.

## 10. Out of scope (V1)

- Pushing local → prod.
- Selective sync (last N days, only certain rows).
- Anonymization / PII scrubbing.
- Auto-pull on `uv run python -m solo` startup. Stays explicit.
- A `--dry-run` flag. Add if it's ever actually useful.
- Restoring from a specific `.bak-*` backup. `mv` works fine.
