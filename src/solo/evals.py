"""Classifier eval scoring — pure functions.

No IO, no LLM. Score per-row predictions against labeled ground truth,
then aggregate into a summary + confusion matrix.
"""

_PRIORITY_ORDER = {"low": 0, "medium": 1, "high": 2}


def score_kind(predicted: str, actual: str) -> bool:
    return predicted == actual


def score_priority(predicted: str, actual: str) -> tuple[bool, int]:
    """Returns (exact_match, ordinal_distance) on low<medium<high."""
    distance = abs(_PRIORITY_ORDER[predicted] - _PRIORITY_ORDER[actual])
    return distance == 0, distance


_KINDS = ("idea", "soft_task", "hard_task", "note")


def build_confusion(rows: list[dict]) -> dict[str, dict[str, int]]:
    """Confusion matrix keyed by [actual_kind][predicted_kind] -> count."""
    matrix: dict[str, dict[str, int]] = {a: {p: 0 for p in _KINDS} for a in _KINDS}
    for row in rows:
        matrix[row["actual_kind"]][row["predicted_kind"]] += 1
    return matrix


def summarize(rows: list[dict]) -> dict:
    """Aggregate per-row results into a summary dict. Pure; no rendering."""
    total = len(rows)
    if total == 0:
        return {
            "total": 0,
            "kind_accuracy": 0.0,
            "priority_accuracy": 0.0,
            "priority_off_by_one": 0.0,
            "priority_off_by_two": 0.0,
            "confusion": {},
        }
    kind_correct = sum(1 for r in rows if r["kind_correct"])
    p_exact = sum(1 for r in rows if r["priority_distance"] == 0)
    p_off_by_1 = sum(1 for r in rows if r["priority_distance"] == 1)
    p_off_by_2 = sum(1 for r in rows if r["priority_distance"] == 2)
    return {
        "total": total,
        "kind_accuracy": kind_correct / total,
        "priority_accuracy": p_exact / total,
        "priority_off_by_one": p_off_by_1 / total,
        "priority_off_by_two": p_off_by_2 / total,
        "confusion": build_confusion(rows),
    }
