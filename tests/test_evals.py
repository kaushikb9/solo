def test_score_kind_match():
    from solo.evals import score_kind

    assert score_kind("idea", "idea") is True


def test_score_kind_mismatch():
    from solo.evals import score_kind

    assert score_kind("idea", "note") is False


def test_score_priority_exact_returns_distance_zero():
    from solo.evals import score_priority

    correct, distance = score_priority("high", "high")
    assert correct is True
    assert distance == 0


def test_score_priority_off_by_one():
    from solo.evals import score_priority

    correct, distance = score_priority("medium", "high")
    assert correct is False
    assert distance == 1


def test_score_priority_off_by_two():
    from solo.evals import score_priority

    correct, distance = score_priority("low", "high")
    assert correct is False
    assert distance == 2


def test_build_confusion_shape_and_counts():
    from solo.evals import build_confusion

    rows = [
        {"actual_kind": "idea", "predicted_kind": "idea"},
        {"actual_kind": "idea", "predicted_kind": "note"},
        {"actual_kind": "soft_task", "predicted_kind": "soft_task"},
        {"actual_kind": "hard_task", "predicted_kind": "hard_task"},
        {"actual_kind": "note", "predicted_kind": "note"},
    ]
    m = build_confusion(rows)

    kinds = {"idea", "soft_task", "hard_task", "note"}
    assert set(m.keys()) == kinds
    for actual_row in m.values():
        assert set(actual_row.keys()) == kinds

    assert m["idea"]["idea"] == 1
    assert m["idea"]["note"] == 1
    assert m["soft_task"]["soft_task"] == 1
    assert m["hard_task"]["hard_task"] == 1
    assert m["note"]["note"] == 1
    assert m["soft_task"]["idea"] == 0


def test_summarize_empty_returns_zeros():
    from solo.evals import summarize

    s = summarize([])
    assert s["total"] == 0
    assert s["kind_accuracy"] == 0.0
    assert s["priority_accuracy"] == 0.0
    assert s["priority_off_by_one"] == 0.0
    assert s["priority_off_by_two"] == 0.0
    assert s["confusion"] == {}


def test_summarize_computes_rates():
    from solo.evals import summarize

    rows = [
        {
            "actual_kind": "idea",
            "predicted_kind": "idea",
            "kind_correct": True,
            "priority_distance": 0,
        },
        {
            "actual_kind": "idea",
            "predicted_kind": "note",
            "kind_correct": False,
            "priority_distance": 1,
        },
        {
            "actual_kind": "soft_task",
            "predicted_kind": "soft_task",
            "kind_correct": True,
            "priority_distance": 2,
        },
        {
            "actual_kind": "note",
            "predicted_kind": "note",
            "kind_correct": True,
            "priority_distance": 0,
        },
    ]
    s = summarize(rows)
    assert s["total"] == 4
    assert s["kind_accuracy"] == 0.75
    assert s["priority_accuracy"] == 0.5
    assert s["priority_off_by_one"] == 0.25
    assert s["priority_off_by_two"] == 0.25


def test_summarize_includes_confusion():
    from solo.evals import summarize

    rows = [
        {
            "actual_kind": "idea",
            "predicted_kind": "note",
            "kind_correct": False,
            "priority_distance": 0,
        },
    ]
    s = summarize(rows)
    assert s["confusion"]["idea"]["note"] == 1
