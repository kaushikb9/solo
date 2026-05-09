import pytest


class TestComputeCost:
    def test_known_model_returns_cost(self):
        from solo.llm import compute_cost

        # minimax/minimax-m2.7: $0.30 / $1.20 per M tokens
        # 1000 input + 500 output = 0.0003 + 0.0006 = 0.0009
        cost = compute_cost("minimax/minimax-m2.7", 1000, 500)
        assert cost == pytest.approx(0.0009)

    def test_unknown_model_returns_none(self):
        from solo.llm import compute_cost

        assert compute_cost("does/not-exist", 1000, 500) is None

    def test_zero_tokens_zero_cost(self):
        from solo.llm import compute_cost

        assert compute_cost("minimax/minimax-m2.7", 0, 0) == 0.0
