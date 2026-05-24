def test_top_empty_returns_empty():
    from solo.rank import top

    assert top([]) == []


def test_top_orders_by_priority_then_recency():
    from solo.rank import top

    rows = [
        {"id": 1, "priority": "low", "created_at": "2026-05-22T10:00:00Z"},
        {"id": 2, "priority": "high", "created_at": "2026-05-20T10:00:00Z"},
        {"id": 3, "priority": "medium", "created_at": "2026-05-23T10:00:00Z"},
        {"id": 4, "priority": "high", "created_at": "2026-05-23T11:00:00Z"},
    ]
    out = top(rows)
    assert [r["id"] for r in out] == [4, 2, 3]


def test_top_caps_at_three():
    from solo.rank import top

    rows = [
        {"id": i, "priority": "high", "created_at": f"2026-05-23T{i:02d}:00:00Z"} for i in range(10)
    ]
    out = top(rows)
    assert len(out) == 3


def test_top_unknown_priority_sorts_to_bottom():
    from solo.rank import top

    rows = [
        {"id": 1, "priority": "bogus", "created_at": "2026-05-23T11:00:00Z"},
        {"id": 2, "priority": "low", "created_at": "2026-05-23T10:00:00Z"},
    ]
    out = top(rows)
    assert [r["id"] for r in out] == [2, 1]


def test_top_unknown_priority_below_known_with_same_timestamp():
    from solo.rank import top

    rows = [
        {"id": 1, "priority": "bogus", "created_at": "2026-05-23T10:00:00Z"},
        {"id": 2, "priority": "low", "created_at": "2026-05-23T10:00:00Z"},
    ]
    out = top(rows)
    assert [r["id"] for r in out] == [2, 1]


def test_top_ties_broken_by_id_desc():
    from solo.rank import top

    rows = [
        {"id": 1, "priority": "high", "created_at": "2026-05-23T10:00:00Z"},
        {"id": 2, "priority": "high", "created_at": "2026-05-23T10:00:00Z"},
        {"id": 3, "priority": "high", "created_at": "2026-05-23T10:00:00Z"},
    ]
    out = top(rows)
    assert [r["id"] for r in out] == [3, 2, 1]
