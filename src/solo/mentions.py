"""Extract @-mentions from raw entry text.

Pure module. Used at insert_entry time to populate the `mentions` column,
which the /list and /top3 formatters render as a 👥 marker.
"""

import re

_MENTION_RE = re.compile(r"@(\w+)")


def extract(raw_text: str) -> list[str]:
    """Return @-mentions in first-appearance order, lower-cased, deduped."""
    seen: dict[str, None] = {}
    for m in _MENTION_RE.findall(raw_text):
        seen.setdefault(m.lower(), None)
    return list(seen)
