# Prod → local DB sync — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `scripts/pull_prod_db.py` — a one-shot, on-demand command that pulls a consistent SQLite snapshot from the Railway-hosted prod DB and swaps it into `data/solo.db`, keeping the previous local DB as a timestamped backup (last 3 retained).

**Architecture:** Pure-Python orchestration script. Uses `railway ssh` to invoke `sqlite3 .backup` inside the container, streams the snapshot back base64-encoded over the ssh channel, integrity-checks it, then atomically swaps it into place. No new runtime deps; no changes to `src/solo/`.

**Tech Stack:** Python 3.12 stdlib (`subprocess`, `pathlib`, `base64`, `sqlite3`, `shutil`, `datetime`, `sys`, `json`) + the locally-installed `railway` CLI. Tests use `pytest` + `pytest`'s `tmp_path` fixture + `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-05-26-prod-db-sync-design.md`

---

## File Structure

- `scripts/pull_prod_db.py` — NEW. The entire script: helpers + `main()`. Single module so it's easy to read end-to-end.
- `tests/test_pull_prod_db.py` — NEW. Unit tests against the helpers. Import the script as a module via the `pythonpath` config below.
- `pyproject.toml` — MODIFY. Add `pythonpath = ["scripts"]` under `[tool.pytest.ini_options]` so `tests/` can `import pull_prod_db`.
- `docs/decisions/0009-prod-db-sync-via-railway-ssh.md` — NEW. Short ADR per AGENTS.md conventions.
- `AGENTS.md` — MODIFY. One line under "Common commands".
- `docs/status.md` — MODIFY. Note the new dev tool under the current slice.

The whole script is < 200 lines; keeping it in one file matches `scripts/eval.py`'s shape and is easy to hold in context.

---

## Task 1: ADR-0009

**Files:**
- Create: `docs/decisions/0009-prod-db-sync-via-railway-ssh.md`

- [ ] **Step 1: Write the ADR**

```markdown
# 0009 — Prod → local DB sync uses `railway ssh` + `sqlite3 .backup`

**Status:** accepted
**Date:** 2026-05-26

## Context

After ~30 captured entries kb wants to test local changes against real prod data instead of a stale local DB. Three plausible paths:

1. **On-demand `railway ssh` + `sqlite3 .backup`** — script invokes `railway ssh`, snapshots the prod DB inside the container, streams it down base64-encoded, swaps into place.
2. **Continuous replication (Litestream)** — run Litestream inside the Railway container replicating SQLite to S3/Backblaze; local script downloads latest snapshot.
3. **Bot-side `/dump` Telegram command** — admin command that DM's the DB back to kb.

## Decision

Shape 1. A single script `scripts/pull_prod_db.py` invoked on demand.

## Consequences

**Easier:**
- No new runtime deps in the bot; no external bucket; no secrets to manage.
- Uses tools already on kb's laptop (`railway` CLI, `sqlite3`, Python).
- `sqlite3 .backup` is online and WAL-safe — the bot can keep capturing during the snapshot.
- Easy to extend later (e.g. add `--dry-run`, filtering) without changing the runtime.

**Harder:**
- Requires `railway` CLI to be installed and logged in on the puller's machine. Acceptable — this is a personal dev tool.
- Binary-over-ssh needs base64 wrapping (websocket-backed channel is not guaranteed binary-safe). Adds ~33% transfer overhead; the DB is ~0.1 GB so this is fine.
- Pull is manual; local DB drifts between pulls. Matches kb's stated preference ("on-demand script").

## Alternatives considered

- **Litestream** — rejected. Adds a runtime dep to prod, an external bucket, and secrets. Overkill for on-demand pulls; revisit if continuous local replication is ever wanted.
- **Bot-side `/dump`** — rejected. Violates "capture must never fail" by adding surface area near the bot; sending the whole DB through Telegram is a security smell.
```

- [ ] **Step 2: Commit**

```bash
git add docs/decisions/0009-prod-db-sync-via-railway-ssh.md
git commit -m "docs(adr): 0009 prod-db sync via railway ssh"
```

---

## Task 2: Enable importing `scripts/` from tests

**Files:**
- Modify: `pyproject.toml` (`[tool.pytest.ini_options]` block)

- [ ] **Step 1: Add `pythonpath` to pytest config**

In `pyproject.toml`, change:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
```

to:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["scripts"]
```

- [ ] **Step 2: Verify existing tests still run**

Run: `uv run pytest -q`
Expected: same pass/fail count as before the change. No new failures.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore(test): add scripts/ to pytest pythonpath"
```

---

## Task 3: Script skeleton + `PullError`

**Files:**
- Create: `scripts/pull_prod_db.py`
- Test: `tests/test_pull_prod_db.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pull_prod_db.py`:

```python
import pull_prod_db


def test_pull_error_is_exception():
    assert issubclass(pull_prod_db.PullError, Exception)


def test_module_exposes_main():
    assert callable(pull_prod_db.main)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pull_prod_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pull_prod_db'`.

- [ ] **Step 3: Create the skeleton**

Create `scripts/pull_prod_db.py`:

```python
"""Pull the prod SQLite DB from Railway down to local `data/solo.db`.

Usage:
    uv run python scripts/pull_prod_db.py

Steps:
    1. Preflight: verify `railway` CLI is on PATH and linked to project=solo, service=solo.
    2. Remote snapshot: `railway ssh` → `sqlite3 .backup` → base64 to stdout.
    3. Decode + integrity-check the downloaded snapshot.
    4. Move existing `data/solo.db` (+ -wal/-shm siblings) to `data/solo.db.bak-<UTC-timestamp>`.
       Prune to the 3 most recent backups.
    5. Atomic rename of the snapshot into `data/solo.db`.
    6. Print row counts + size.

Recovery: if the script crashes between the backup rename and the swap-in rename,
both `data/solo.snapshot.tmp` and `data/solo.db.bak-<ts>` exist. Recover with:
    mv data/solo.snapshot.tmp data/solo.db
"""

from __future__ import annotations

import sys


class PullError(Exception):
    """Raised on any failure during the prod-db pull. Caught only in main()."""


def main() -> int:
    """Orchestration entry point. Returns shell exit code."""
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pull_prod_db.py -v`
Expected: PASS, 2 tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/pull_prod_db.py tests/test_pull_prod_db.py
git commit -m "feat(scripts): pull_prod_db skeleton with PullError"
```

---

## Task 4: `rotate_backups` helper (TDD)

This is the trickiest pure-logic helper. It moves the current DB to a timestamped backup and prunes older backups to keep only the 3 most recent. Each backup carries its `-wal` and `-shm` siblings along.

**Files:**
- Modify: `scripts/pull_prod_db.py`
- Modify: `tests/test_pull_prod_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pull_prod_db.py`:

```python
from pathlib import Path

import pytest

import pull_prod_db


def _touch(p: Path, content: bytes = b"") -> Path:
    p.write_bytes(content)
    return p


class TestRotateBackups:
    def test_no_current_db_is_noop(self, tmp_path: Path):
        result = pull_prod_db.rotate_backups(tmp_path, keep=3, now_suffix="20260526-120000")
        assert result is None
        assert list(tmp_path.iterdir()) == []

    def test_moves_db_to_timestamped_backup(self, tmp_path: Path):
        _touch(tmp_path / "solo.db", b"DBDATA")
        backup = pull_prod_db.rotate_backups(tmp_path, keep=3, now_suffix="20260526-120000")
        assert backup == tmp_path / "solo.db.bak-20260526-120000"
        assert backup.exists()
        assert backup.read_bytes() == b"DBDATA"
        assert not (tmp_path / "solo.db").exists()

    def test_moves_wal_and_shm_siblings(self, tmp_path: Path):
        _touch(tmp_path / "solo.db", b"D")
        _touch(tmp_path / "solo.db-wal", b"W")
        _touch(tmp_path / "solo.db-shm", b"S")
        backup = pull_prod_db.rotate_backups(tmp_path, keep=3, now_suffix="20260526-120000")
        assert backup is not None
        assert (tmp_path / "solo.db.bak-20260526-120000").read_bytes() == b"D"
        assert (tmp_path / "solo.db.bak-20260526-120000-wal").read_bytes() == b"W"
        assert (tmp_path / "solo.db.bak-20260526-120000-shm").read_bytes() == b"S"
        assert not (tmp_path / "solo.db-wal").exists()
        assert not (tmp_path / "solo.db-shm").exists()

    def test_prunes_to_keep_count(self, tmp_path: Path):
        for ts in ("20260520-090000", "20260521-090000", "20260522-090000", "20260523-090000"):
            _touch(tmp_path / f"solo.db.bak-{ts}")
        _touch(tmp_path / "solo.db", b"NEW")
        pull_prod_db.rotate_backups(tmp_path, keep=3, now_suffix="20260524-090000")
        names = sorted(p.name for p in tmp_path.iterdir())
        assert names == [
            "solo.db.bak-20260522-090000",
            "solo.db.bak-20260523-090000",
            "solo.db.bak-20260524-090000",
        ]

    def test_prunes_wal_and_shm_with_parent(self, tmp_path: Path):
        for ts in ("20260520-090000", "20260521-090000", "20260522-090000", "20260523-090000"):
            _touch(tmp_path / f"solo.db.bak-{ts}")
            _touch(tmp_path / f"solo.db.bak-{ts}-wal")
            _touch(tmp_path / f"solo.db.bak-{ts}-shm")
        _touch(tmp_path / "solo.db", b"NEW")
        pull_prod_db.rotate_backups(tmp_path, keep=3, now_suffix="20260524-090000")
        # 20260520 should be fully gone (parent + siblings)
        assert not (tmp_path / "solo.db.bak-20260520-090000").exists()
        assert not (tmp_path / "solo.db.bak-20260520-090000-wal").exists()
        assert not (tmp_path / "solo.db.bak-20260520-090000-shm").exists()

    def test_keep_zero_prunes_everything_including_new_backup(self, tmp_path: Path):
        _touch(tmp_path / "solo.db", b"NEW")
        pull_prod_db.rotate_backups(tmp_path, keep=0, now_suffix="20260524-090000")
        assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pull_prod_db.py::TestRotateBackups -v`
Expected: FAIL — `AttributeError: module 'pull_prod_db' has no attribute 'rotate_backups'`.

- [ ] **Step 3: Implement `rotate_backups`**

Add to `scripts/pull_prod_db.py` (after `PullError`, before `main`):

```python
from pathlib import Path

DB_FILENAME = "solo.db"
BACKUP_PREFIX = f"{DB_FILENAME}.bak-"
SIBLING_SUFFIXES = ("-wal", "-shm")


def rotate_backups(data_dir: Path, *, keep: int, now_suffix: str) -> Path | None:
    """Move current `solo.db` (+ -wal/-shm) to a timestamped backup, then prune.

    Returns the new backup path, or None if there was no current DB to back up.
    Prunes `solo.db.bak-*` so that only the `keep` most recent (lexicographic on
    the timestamp suffix) remain, including the one just created. WAL/SHM
    siblings of pruned backups are pruned alongside their parent.
    """
    current = data_dir / DB_FILENAME
    new_backup: Path | None = None
    if current.exists():
        new_backup = data_dir / f"{BACKUP_PREFIX}{now_suffix}"
        current.rename(new_backup)
        for suffix in SIBLING_SUFFIXES:
            sibling = data_dir / f"{DB_FILENAME}{suffix}"
            if sibling.exists():
                sibling.rename(data_dir / f"{BACKUP_PREFIX}{now_suffix}{suffix}")

    # Discover existing parent backups (exclude sibling files by requiring
    # the name to end exactly with the timestamp — no extra suffix).
    parents = sorted(
        p for p in data_dir.glob(f"{BACKUP_PREFIX}*")
        if not any(p.name.endswith(s) for s in SIBLING_SUFFIXES)
    )
    while len(parents) > keep:
        victim = parents.pop(0)
        victim.unlink()
        for suffix in SIBLING_SUFFIXES:
            sib = victim.parent / f"{victim.name}{suffix}"
            if sib.exists():
                sib.unlink()

    return new_backup
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pull_prod_db.py::TestRotateBackups -v`
Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/pull_prod_db.py tests/test_pull_prod_db.py
git commit -m "feat(scripts): rotate_backups helper for pull_prod_db"
```

---

## Task 5: `verify_snapshot` helper (TDD)

**Files:**
- Modify: `scripts/pull_prod_db.py`
- Modify: `tests/test_pull_prod_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pull_prod_db.py`:

```python
import sqlite3


def _make_db_with_entries(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE entries (id INTEGER PRIMARY KEY, raw_text TEXT)")
    conn.execute("INSERT INTO entries (raw_text) VALUES ('hi')")
    conn.commit()
    conn.close()


def _make_db_without_entries(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE other (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()


class TestVerifySnapshot:
    def test_passes_on_valid_db_with_entries(self, tmp_path: Path):
        p = tmp_path / "snap.db"
        _make_db_with_entries(p)
        pull_prod_db.verify_snapshot(p)  # does not raise

    def test_raises_on_missing_entries_table(self, tmp_path: Path):
        p = tmp_path / "snap.db"
        _make_db_without_entries(p)
        with pytest.raises(pull_prod_db.PullError, match="entries"):
            pull_prod_db.verify_snapshot(p)

    def test_raises_on_truncated_file(self, tmp_path: Path):
        p = tmp_path / "snap.db"
        _make_db_with_entries(p)
        data = p.read_bytes()
        p.write_bytes(data[: len(data) // 2])  # truncate
        with pytest.raises(pull_prod_db.PullError):
            pull_prod_db.verify_snapshot(p)

    def test_raises_on_non_db_file(self, tmp_path: Path):
        p = tmp_path / "snap.db"
        p.write_bytes(b"this is not a sqlite database")
        with pytest.raises(pull_prod_db.PullError):
            pull_prod_db.verify_snapshot(p)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pull_prod_db.py::TestVerifySnapshot -v`
Expected: FAIL — `verify_snapshot` does not exist.

- [ ] **Step 3: Implement `verify_snapshot`**

Add to `scripts/pull_prod_db.py`:

```python
import sqlite3


def verify_snapshot(path: Path) -> None:
    """Raise PullError if `path` is not a valid SQLite DB with an `entries` table."""
    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error as e:
        raise PullError(f"cannot open snapshot at {path}: {e}") from e

    try:
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.DatabaseError as e:
            raise PullError(f"snapshot at {path} is not a valid SQLite DB: {e}") from e
        if not row or row[0] != "ok":
            raise PullError(f"integrity_check failed for {path}: {row[0] if row else 'no result'}")

        cur = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='entries'"
        )
        if cur.fetchone() is None:
            raise PullError(f"snapshot at {path} has no `entries` table")
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pull_prod_db.py::TestVerifySnapshot -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/pull_prod_db.py tests/test_pull_prod_db.py
git commit -m "feat(scripts): verify_snapshot integrity check"
```

---

## Task 6: `preflight` (TDD with mocked `subprocess`)

**Files:**
- Modify: `scripts/pull_prod_db.py`
- Modify: `tests/test_pull_prod_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pull_prod_db.py`:

```python
import json
from unittest.mock import patch


class TestPreflight:
    def test_passes_when_status_shows_solo_project_and_service(self):
        status_payload = {
            "project": {"name": "solo"},
            "service": {"name": "solo"},
        }
        with patch("pull_prod_db.shutil.which", return_value="/usr/local/bin/railway"), \
             patch("pull_prod_db.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = json.dumps(status_payload)
            mock_run.return_value.stderr = ""
            pull_prod_db.preflight()  # does not raise

    def test_fails_when_railway_not_on_path(self):
        with patch("pull_prod_db.shutil.which", return_value=None):
            with pytest.raises(pull_prod_db.PullError, match="railway"):
                pull_prod_db.preflight()

    def test_fails_when_status_returns_non_zero(self):
        with patch("pull_prod_db.shutil.which", return_value="/usr/local/bin/railway"), \
             patch("pull_prod_db.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = "not linked"
            with pytest.raises(pull_prod_db.PullError, match="railway link"):
                pull_prod_db.preflight()

    def test_fails_when_project_is_wrong(self):
        status_payload = {"project": {"name": "other-project"}, "service": {"name": "solo"}}
        with patch("pull_prod_db.shutil.which", return_value="/usr/local/bin/railway"), \
             patch("pull_prod_db.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = json.dumps(status_payload)
            with pytest.raises(pull_prod_db.PullError, match="project"):
                pull_prod_db.preflight()

    def test_fails_when_service_is_missing(self):
        status_payload = {"project": {"name": "solo"}}
        with patch("pull_prod_db.shutil.which", return_value="/usr/local/bin/railway"), \
             patch("pull_prod_db.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = json.dumps(status_payload)
            with pytest.raises(pull_prod_db.PullError, match="service"):
                pull_prod_db.preflight()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pull_prod_db.py::TestPreflight -v`
Expected: FAIL — `preflight` does not exist.

- [ ] **Step 3: Implement `preflight`**

Add imports + function to `scripts/pull_prod_db.py`:

```python
import json
import shutil
import subprocess

EXPECTED_PROJECT = "solo"
EXPECTED_SERVICE = "solo"


def preflight() -> None:
    """Verify the `railway` CLI is installed and linked to project=solo, service=solo."""
    if shutil.which("railway") is None:
        raise PullError(
            "railway CLI not found on PATH.\n"
            "Install it: https://docs.railway.com/guides/cli\n"
            "Then run: railway login && railway link"
        )

    proc = subprocess.run(
        ["railway", "status", "--json"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise PullError(
            "`railway status --json` failed. Fix with:\n"
            "  railway login && railway link  # select project=solo, service=solo\n"
            f"stderr: {proc.stderr.strip()}"
        )

    try:
        status = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise PullError(f"could not parse `railway status --json` output: {e}") from e

    project_name = (status.get("project") or {}).get("name")
    if project_name != EXPECTED_PROJECT:
        raise PullError(
            f"linked railway project is {project_name!r}, expected {EXPECTED_PROJECT!r}. "
            f"Run `railway link` and select the {EXPECTED_PROJECT!r} project."
        )

    service_name = (status.get("service") or {}).get("name")
    if service_name != EXPECTED_SERVICE:
        raise PullError(
            f"linked railway service is {service_name!r}, expected {EXPECTED_SERVICE!r}. "
            f"Run `railway service` and select {EXPECTED_SERVICE!r}."
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pull_prod_db.py::TestPreflight -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/pull_prod_db.py tests/test_pull_prod_db.py
git commit -m "feat(scripts): preflight verifies railway link"
```

---

## Task 7: `fetch_snapshot` (TDD with mocked `subprocess`)

**Files:**
- Modify: `scripts/pull_prod_db.py`
- Modify: `tests/test_pull_prod_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pull_prod_db.py`:

```python
import base64


class TestFetchSnapshot:
    def test_decodes_base64_stdout_to_bytes(self):
        payload = b"\x00\x01\x02SQLITE\xff"
        b64 = base64.b64encode(payload).decode()
        with patch("pull_prod_db.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = b64 + "\n"
            mock_run.return_value.stderr = ""
            result = pull_prod_db.fetch_snapshot()
        assert result == payload

    def test_raises_on_non_zero_exit(self):
        with patch("pull_prod_db.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = "connection refused"
            with pytest.raises(pull_prod_db.PullError, match="railway ssh"):
                pull_prod_db.fetch_snapshot()

    def test_raises_on_empty_stdout(self):
        with patch("pull_prod_db.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = ""
            with pytest.raises(pull_prod_db.PullError, match="empty"):
                pull_prod_db.fetch_snapshot()

    def test_raises_on_invalid_base64(self):
        with patch("pull_prod_db.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "not!valid!base64!!!"
            mock_run.return_value.stderr = ""
            with pytest.raises(pull_prod_db.PullError, match="base64"):
                pull_prod_db.fetch_snapshot()

    def test_invokes_correct_railway_command(self):
        payload = b"X"
        b64 = base64.b64encode(payload).decode()
        with patch("pull_prod_db.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = b64
            mock_run.return_value.stderr = ""
            pull_prod_db.fetch_snapshot()
        args, kwargs = mock_run.call_args
        cmd = args[0]
        assert cmd[0] == "railway"
        assert cmd[1] == "ssh"
        # The remote command should reference the prod db path and base64 it
        remote_cmd = " ".join(cmd[2:])
        assert "/app/data/solo.db" in remote_cmd
        assert ".backup" in remote_cmd
        assert "base64" in remote_cmd
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pull_prod_db.py::TestFetchSnapshot -v`
Expected: FAIL — `fetch_snapshot` does not exist.

- [ ] **Step 3: Implement `fetch_snapshot`**

Add to `scripts/pull_prod_db.py`:

```python
import base64

REMOTE_DB_PATH = "/app/data/solo.db"
REMOTE_SNAPSHOT_PATH = "/tmp/solo-snap.db"

_REMOTE_CMD = (
    f"sqlite3 {REMOTE_DB_PATH} \".backup {REMOTE_SNAPSHOT_PATH}\" && "
    f"base64 {REMOTE_SNAPSHOT_PATH} && "
    f"rm -f {REMOTE_SNAPSHOT_PATH}"
)


def fetch_snapshot() -> bytes:
    """Take a consistent snapshot of the prod DB and return its bytes."""
    proc = subprocess.run(
        ["railway", "ssh", _REMOTE_CMD],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise PullError(
            f"`railway ssh` failed (exit {proc.returncode}):\n"
            f"stderr: {proc.stderr.strip()}"
        )
    if not proc.stdout.strip():
        raise PullError("`railway ssh` returned empty stdout — nothing to decode")

    try:
        return base64.b64decode(proc.stdout, validate=True)
    except (ValueError, base64.binascii.Error) as e:
        raise PullError(f"base64 decode failed: {e}") from e
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pull_prod_db.py::TestFetchSnapshot -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/pull_prod_db.py tests/test_pull_prod_db.py
git commit -m "feat(scripts): fetch_snapshot via railway ssh + base64"
```

---

## Task 8: `swap_in` + `report` (TDD)

**Files:**
- Modify: `scripts/pull_prod_db.py`
- Modify: `tests/test_pull_prod_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pull_prod_db.py`:

```python
class TestSwapIn:
    def test_renames_tmp_to_target(self, tmp_path: Path):
        tmp = tmp_path / "snap.tmp"
        tmp.write_bytes(b"NEW")
        target = tmp_path / "solo.db"
        pull_prod_db.swap_in(tmp, target)
        assert not tmp.exists()
        assert target.read_bytes() == b"NEW"

    def test_raises_if_tmp_missing(self, tmp_path: Path):
        with pytest.raises(pull_prod_db.PullError):
            pull_prod_db.swap_in(tmp_path / "missing.tmp", tmp_path / "solo.db")


class TestReport:
    def test_prints_counts_and_paths(self, tmp_path: Path, capsys):
        db = tmp_path / "solo.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE entries (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE llm_calls (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO entries DEFAULT VALUES")
        conn.execute("INSERT INTO entries DEFAULT VALUES")
        conn.execute("INSERT INTO llm_calls DEFAULT VALUES")
        conn.commit()
        conn.close()
        backup = tmp_path / "solo.db.bak-20260526-120000"
        backup.write_bytes(b"OLD")

        pull_prod_db.report(db, backup, pruned=2, keep=3)

        out = capsys.readouterr().out
        assert "entries:   2" in out
        assert "llm_calls: 1" in out
        assert str(db) in out
        assert str(backup) in out

    def test_handles_no_backup(self, tmp_path: Path, capsys):
        db = tmp_path / "solo.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE entries (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE llm_calls (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        pull_prod_db.report(db, None, pruned=0, keep=3)

        out = capsys.readouterr().out
        assert "entries:   0" in out
        assert "no previous local DB to back up" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pull_prod_db.py::TestSwapIn tests/test_pull_prod_db.py::TestReport -v`
Expected: FAIL — functions do not exist.

- [ ] **Step 3: Implement `swap_in` and `report`**

Add to `scripts/pull_prod_db.py`:

```python
def swap_in(snapshot_tmp: Path, target: Path) -> None:
    """Atomically rename the verified snapshot into the target DB path."""
    if not snapshot_tmp.exists():
        raise PullError(f"snapshot tmp file not found: {snapshot_tmp}")
    snapshot_tmp.rename(target)
    # Stale WAL/SHM files from the previous DB would silently shadow the new one;
    # the snapshot is fully checkpointed, so they're safe to remove.
    for suffix in SIBLING_SUFFIXES:
        stale = target.parent / f"{target.name}{suffix}"
        if stale.exists():
            stale.unlink()


def _format_size(n_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n_bytes < 1024 or unit == "GB":
            return f"{n_bytes:.1f} {unit}" if unit != "B" else f"{n_bytes} {unit}"
        n_bytes /= 1024
    return f"{n_bytes:.1f} GB"


def report(db_path: Path, backup: Path | None, *, pruned: int, keep: int) -> None:
    """Print a success summary: row counts, size, backup path."""
    conn = sqlite3.connect(db_path)
    try:
        entries_n = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        try:
            llm_n = conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0]
        except sqlite3.OperationalError:
            llm_n = 0  # trace table may not exist on a fresh DB
    finally:
        conn.close()

    print(f"pulled prod DB → {db_path}")
    print(f"  entries:   {entries_n}")
    print(f"  llm_calls: {llm_n}")
    print(f"  size:      {_format_size(db_path.stat().st_size)}")
    if backup is not None:
        print(f"backup kept at {backup}")
    else:
        print("no previous local DB to back up")
    if pruned > 0:
        print(f"pruned {pruned} old backup(s) (kept {keep} most recent)")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pull_prod_db.py::TestSwapIn tests/test_pull_prod_db.py::TestReport -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/pull_prod_db.py tests/test_pull_prod_db.py
git commit -m "feat(scripts): swap_in + report helpers"
```

---

## Task 9: `main` orchestration

`main` ties the helpers together. We unit-test the happy path and the error-to-exit-code translation with the lower-level functions mocked.

**Files:**
- Modify: `scripts/pull_prod_db.py`
- Modify: `tests/test_pull_prod_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pull_prod_db.py`:

```python
class TestMain:
    def _setup_mocks(self, tmp_path: Path, payload: bytes):
        """Patch railway / preflight / fetch and return the data dir."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        # seed an existing local DB so the backup branch runs
        (data_dir / "solo.db").write_bytes(b"OLD")
        # a minimal valid SQLite snapshot
        snap_path = tmp_path / "_seed.db"
        _make_db_with_entries(snap_path)
        if payload is None:
            payload = snap_path.read_bytes()
        return data_dir, payload

    def test_happy_path(self, tmp_path: Path, monkeypatch):
        data_dir, payload = self._setup_mocks(tmp_path, payload=None)
        monkeypatch.setattr(pull_prod_db, "DATA_DIR", data_dir)
        monkeypatch.setattr(pull_prod_db, "preflight", lambda: None)
        monkeypatch.setattr(pull_prod_db, "fetch_snapshot", lambda: payload)
        rc = pull_prod_db.main()
        assert rc == 0
        # new DB in place
        assert (data_dir / "solo.db").exists()
        # backup created
        backups = list(data_dir.glob("solo.db.bak-*"))
        assert len(backups) == 1
        assert backups[0].read_bytes() == b"OLD"
        # no leftover tmp file
        assert not (data_dir / "solo.snapshot.tmp").exists()

    def test_preflight_failure_returns_nonzero_and_leaves_db_alone(
        self, tmp_path: Path, monkeypatch, capsys
    ):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "solo.db").write_bytes(b"OLD")
        monkeypatch.setattr(pull_prod_db, "DATA_DIR", data_dir)
        def boom():
            raise pull_prod_db.PullError("railway CLI not found")
        monkeypatch.setattr(pull_prod_db, "preflight", boom)

        rc = pull_prod_db.main()
        assert rc != 0
        assert (data_dir / "solo.db").read_bytes() == b"OLD"
        err = capsys.readouterr().err
        assert "railway CLI not found" in err

    def test_fetch_failure_leaves_db_alone(self, tmp_path: Path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "solo.db").write_bytes(b"OLD")
        monkeypatch.setattr(pull_prod_db, "DATA_DIR", data_dir)
        monkeypatch.setattr(pull_prod_db, "preflight", lambda: None)
        def boom():
            raise pull_prod_db.PullError("railway ssh failed")
        monkeypatch.setattr(pull_prod_db, "fetch_snapshot", boom)

        rc = pull_prod_db.main()
        assert rc != 0
        assert (data_dir / "solo.db").read_bytes() == b"OLD"

    def test_corrupt_snapshot_leaves_db_alone(self, tmp_path: Path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "solo.db").write_bytes(b"OLD")
        monkeypatch.setattr(pull_prod_db, "DATA_DIR", data_dir)
        monkeypatch.setattr(pull_prod_db, "preflight", lambda: None)
        monkeypatch.setattr(pull_prod_db, "fetch_snapshot", lambda: b"not a sqlite file")

        rc = pull_prod_db.main()
        assert rc != 0
        assert (data_dir / "solo.db").read_bytes() == b"OLD"
        # tmp file cleaned up
        assert not (data_dir / "solo.snapshot.tmp").exists()
        # no backup made (we abort before rotate)
        assert list(data_dir.glob("solo.db.bak-*")) == []

    def test_happy_path_with_no_existing_db(self, tmp_path: Path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        snap_path = tmp_path / "_seed.db"
        _make_db_with_entries(snap_path)
        payload = snap_path.read_bytes()
        monkeypatch.setattr(pull_prod_db, "DATA_DIR", data_dir)
        monkeypatch.setattr(pull_prod_db, "preflight", lambda: None)
        monkeypatch.setattr(pull_prod_db, "fetch_snapshot", lambda: payload)

        rc = pull_prod_db.main()
        assert rc == 0
        assert (data_dir / "solo.db").exists()
        assert list(data_dir.glob("solo.db.bak-*")) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pull_prod_db.py::TestMain -v`
Expected: FAIL — `main` raises `NotImplementedError` (and `DATA_DIR` doesn't exist yet).

- [ ] **Step 3: Implement `main`**

Replace the placeholder `main` in `scripts/pull_prod_db.py`:

```python
from datetime import UTC, datetime

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
KEEP_BACKUPS = 3
SNAPSHOT_TMP_NAME = "solo.snapshot.tmp"


def _now_suffix() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def main() -> int:
    try:
        preflight()
        payload = fetch_snapshot()

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        snapshot_tmp = DATA_DIR / SNAPSHOT_TMP_NAME
        snapshot_tmp.write_bytes(payload)
        try:
            verify_snapshot(snapshot_tmp)
        except PullError:
            snapshot_tmp.unlink(missing_ok=True)
            raise

        target = DATA_DIR / DB_FILENAME
        existing_parents_before = sorted(DATA_DIR.glob(f"{BACKUP_PREFIX}*"))
        # Filter siblings out for the pre-count
        existing_parents_before = [
            p for p in existing_parents_before
            if not any(p.name.endswith(s) for s in SIBLING_SUFFIXES)
        ]
        backup = rotate_backups(DATA_DIR, keep=KEEP_BACKUPS, now_suffix=_now_suffix())
        existing_parents_after = sorted(
            p for p in DATA_DIR.glob(f"{BACKUP_PREFIX}*")
            if not any(p.name.endswith(s) for s in SIBLING_SUFFIXES)
        )
        # +1 for the new backup if created; pruning is the delta from the would-be size
        would_be = len(existing_parents_before) + (1 if backup else 0)
        pruned = would_be - len(existing_parents_after)

        swap_in(snapshot_tmp, target)
        report(target, backup, pruned=pruned, keep=KEEP_BACKUPS)
        return 0
    except PullError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pull_prod_db.py::TestMain -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Run the full test file**

Run: `uv run pytest tests/test_pull_prod_db.py -v`
Expected: all tests pass (~28 tests across all classes).

- [ ] **Step 6: Run the whole test suite + lint**

Run:
```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```
Expected: PASS / clean. If `ruff format --check` complains, run `uv run ruff format scripts/pull_prod_db.py tests/test_pull_prod_db.py` and inspect the diff before committing.

- [ ] **Step 7: Commit**

```bash
git add scripts/pull_prod_db.py tests/test_pull_prod_db.py
git commit -m "feat(scripts): main orchestration for pull_prod_db"
```

---

## Task 10: Docs — AGENTS.md + status.md

**Files:**
- Modify: `AGENTS.md` (the "Common commands" code block)
- Modify: `docs/status.md`

- [ ] **Step 1: Add the command to AGENTS.md**

In `AGENTS.md`, locate the "Common commands" block:

```bash
uv sync                              # install deps
uv run python -m solo                # run bot (long polling)
uv run pytest                        # tests
uv run python scripts/eval.py        # classifier eval
uv run ruff check .                  # lint
uv run ruff format .                 # format
```

Add one line at the end:

```bash
uv run python scripts/pull_prod_db.py  # pull prod DB → local data/solo.db
```

- [ ] **Step 2: Update docs/status.md**

In `docs/status.md`, under "Last updated", change the date to `2026-05-26 — by Claude Code (Opus 4.7).` and add a short note under the current state (after the slice 6 manifest, before "Pending manual verification"):

```markdown
**Dev tooling addition (2026-05-26):** `scripts/pull_prod_db.py` — on-demand pull of prod SQLite DB into `data/solo.db`. Keeps the last 3 timestamped backups. Spec at `docs/superpowers/specs/2026-05-26-prod-db-sync-design.md`; ADR-0009.
```

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md docs/status.md
git commit -m "docs: add pull_prod_db.py to common commands + status"
```

---

## Task 11: Live smoke + final verification

This step requires the live Railway link kb already has. Do not skip — it's the only end-to-end verification.

- [ ] **Step 1: Confirm pre-state**

Run:
```bash
ls -la data/
uv run sqlite3 data/solo.db "SELECT COUNT(*) FROM entries;"
```
Note the count and timestamp; you'll cross-check after the pull.

- [ ] **Step 2: Run the pull**

Run: `uv run python scripts/pull_prod_db.py`

Expected output shape:
```
pulled prod DB → /Users/kb/Code/solo/data/solo.db
  entries:   <N>
  llm_calls: <M>
  size:      <X.X MB>
backup kept at /Users/kb/Code/solo/data/solo.db.bak-<UTC-ts>
```

- [ ] **Step 3: Cross-check the pulled DB**

Run: `uv run sqlite3 data/solo.db "SELECT COUNT(*), MAX(created_at) FROM entries;"`
Expected: count matches what `/all` in Telegram shows; latest `created_at` is recent.

- [ ] **Step 4: Confirm the backup file is intact**

Run: `uv run sqlite3 data/solo.db.bak-<ts> "PRAGMA integrity_check;"`
Expected: `ok`.

- [ ] **Step 5: Run the bot against the pulled DB (sanity)**

Run: `uv run python -m solo` in one terminal, send `/list` from your Telegram client.
Expected: list reflects real prod entries.
Kill the bot with Ctrl+C when satisfied.

- [ ] **Step 6: Test backup retention**

Re-run the pull three more times:
```bash
uv run python scripts/pull_prod_db.py
uv run python scripts/pull_prod_db.py
uv run python scripts/pull_prod_db.py
```
Then:
```bash
ls data/solo.db.bak-*
```
Expected: exactly 3 backup files. The fourth pull should have pruned the oldest. The last run's output should include `pruned 1 old backup(s) (kept 3 most recent)`.

- [ ] **Step 7: Run review agents**

Per AGENTS.md, run **both** before claiming done:

```bash
# In Claude Code:
# Use the Agent tool with subagent_type="code-reviewer"
# Use the Agent tool with subagent_type="solo-reviewer"
```

Address any findings.

- [ ] **Step 8: Final commit (if any review fixups landed)**

Only if review surfaced changes:
```bash
git add -A
git commit -m "fix(scripts): address review findings on pull_prod_db"
```

---

## Done criteria

- [ ] `uv run python scripts/pull_prod_db.py` succeeds against the live Railway link.
- [ ] `uv run pytest` is green.
- [ ] `uv run ruff check .` and `uv run ruff format --check .` are clean.
- [ ] `data/solo.db.bak-*` rotation keeps exactly 3 backups after the 4th pull.
- [ ] `code-reviewer` + `solo-reviewer` agents both pass.
- [ ] `AGENTS.md` and `docs/status.md` updated.
- [ ] ADR-0009 committed.
