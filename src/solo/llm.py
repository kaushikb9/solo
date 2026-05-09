"""LLMClient — single observable entry point for every LLM call in solo.

All LLM calls go through this module. Every call writes one row to the
llm_calls trace table.
"""

# Verified at openrouter.ai/models — update on drift.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # (input_per_1m_tokens_usd, output_per_1m_tokens_usd)
    "minimax/minimax-m2.7":  (0.30, 1.20),
    "moonshotai/kimi-k2.5":  (0.44, 2.00),
    "moonshotai/kimi-k2.6":  (0.74, 3.49),
}


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        return None
    in_price, out_price = pricing
    return (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price
