def test_extract_empty_returns_empty_list():
    from solo.mentions import extract

    assert extract("") == []
    assert extract("no mentions here") == []


def test_extract_single_mention():
    from solo.mentions import extract

    assert extract("ping @alice about it") == ["alice"]


def test_extract_multiple_mentions_preserves_order():
    from solo.mentions import extract

    assert extract("loop @alice and @bob on this") == ["alice", "bob"]


def test_extract_dedupes_case_insensitively():
    from solo.mentions import extract

    assert extract("@Alice told @alice and @ALICE") == ["alice"]


def test_extract_handles_trailing_punctuation():
    from solo.mentions import extract

    assert extract("ping @alice, then @bob.") == ["alice", "bob"]


def test_extract_treats_email_local_as_mention():
    from solo.mentions import extract

    # \w+ matches the chars after @, so "kb@example.com" yields ["example"].
    # Documented behavior — emails aren't real mentions but we don't try to detect them.
    assert extract("kb@example.com") == ["example"]
