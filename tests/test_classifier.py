import pytest


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def conn(db_path):
    from solo.db import get_connection

    conn = get_connection(str(db_path))
    yield conn
    conn.close()


class TestClassifyResultSchema:
    def test_valid_payload(self):
        from solo.classifier import ClassifyResult

        r = ClassifyResult(kind="idea", summary="explore X", priority="high")
        assert r.kind == "idea"

    def test_invalid_kind_rejected(self):
        from pydantic import ValidationError

        from solo.classifier import ClassifyResult

        with pytest.raises(ValidationError):
            ClassifyResult(kind="bogus", summary="x", priority="high")

    def test_invalid_priority_rejected(self):
        from pydantic import ValidationError

        from solo.classifier import ClassifyResult

        with pytest.raises(ValidationError):
            ClassifyResult(kind="idea", summary="x", priority="urgent")
