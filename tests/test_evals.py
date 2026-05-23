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
