"""Deterministic ranking for /top3.

Pure functions only. No DB, no LLM. Sort key is (priority desc, created_at desc,
id desc) — the `id` tertiary key makes ties deterministic even when two entries
share a millisecond-precision `created_at`.
"""

_PRIORITY_RANK = {"high": 3, "medium": 2, "low": 1}


def top3(entries: list[dict]) -> list[dict]:
    """Return the 3 highest-priority, most-recent entries.

    Unknown priorities sort below known ones. Ties on (priority, created_at)
    are broken by id desc.
    """
    return sorted(
        entries,
        key=lambda r: (
            _PRIORITY_RANK.get(r["priority"], 0),
            r["created_at"],
            r.get("id", 0),
        ),
        reverse=True,
    )[:3]
