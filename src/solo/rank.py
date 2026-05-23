"""Deterministic ranking for /top3.

Pure functions only. No DB, no LLM. Sorts by (priority desc, created_at desc).
"""

_PRIORITY_RANK = {"high": 3, "medium": 2, "low": 1}


def top3(entries: list[dict]) -> list[dict]:
    """Return the 3 highest-priority, most-recent entries.

    Unknown priorities sort below known ones.
    """
    return sorted(
        entries,
        key=lambda r: (_PRIORITY_RANK.get(r["priority"], 0), r["created_at"]),
        reverse=True,
    )[:3]
