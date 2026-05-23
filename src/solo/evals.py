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
