"""
tests/test_llm_pricing.py — Tests for LLM cost calculation.

Verifies that calculate_cost() returns accurate USD costs for known
token counts, and that unknown models raise KeyError (we want to fail
loudly rather than silently logging $0.00).

See NFR-OB-1: cost must match the provider's bill within 1%.
"""

import pytest

from backend.llm.pricing import calculate_cost, MODEL_PRICING


class TestCalculateCost:
    """Tests for the calculate_cost function."""

    def test_claude_sonnet_cost(self):
        """
        Claude Sonnet 4.6: $3/M input, $15/M output.
        1000 input tokens = $0.003, 500 output tokens = $0.0075.
        Total = $0.0105.
        """
        cost = calculate_cost("claude-sonnet-4-6", input_tokens=1000, output_tokens=500)
        assert abs(cost - 0.0105) < 0.0001

    def test_claude_opus_cost(self):
        """
        Claude Opus 4.6: $15/M input, $75/M output.
        1000 input tokens = $0.015, 500 output tokens = $0.0375.
        Total = $0.0525.
        """
        cost = calculate_cost("claude-opus-4-6", input_tokens=1000, output_tokens=500)
        assert abs(cost - 0.0525) < 0.0001

    def test_gpt4o_cost(self):
        """
        GPT-4o: $2.50/M input, $10/M output.
        1000 input tokens = $0.0025, 500 output tokens = $0.005.
        Total = $0.0075.
        """
        cost = calculate_cost("gpt-4o", input_tokens=1000, output_tokens=500)
        assert abs(cost - 0.0075) < 0.0001

    def test_gpt41_cost(self):
        """
        GPT-4.1: $2/M input, $8/M output.
        1000 input tokens = $0.002, 500 output tokens = $0.004.
        Total = $0.006.
        """
        cost = calculate_cost("gpt-4.1", input_tokens=1000, output_tokens=500)
        assert abs(cost - 0.006) < 0.0001

    def test_zero_tokens(self):
        """Zero tokens should cost $0."""
        cost = calculate_cost("claude-sonnet-4-6", input_tokens=0, output_tokens=0)
        assert cost == 0.0

    def test_unknown_model_raises(self):
        """Unknown models must raise KeyError — never silently return $0."""
        with pytest.raises(KeyError, match="not found in pricing table"):
            calculate_cost("unknown-model-xyz", input_tokens=100, output_tokens=50)

    def test_all_models_have_positive_pricing(self):
        """Every model in the pricing table must have positive costs."""
        for model_name, pricing in MODEL_PRICING.items():
            assert pricing.input_cost_per_token > 0, f"{model_name} has zero input cost"
            assert pricing.output_cost_per_token > 0, f"{model_name} has zero output cost"

    def test_realistic_extraction_cost(self):
        """
        Realistic extraction call: ~850 input tokens, ~320 output tokens.
        Claude Sonnet 4.6: ($3 * 850 + $15 * 320) / 1M = $0.00735.
        """
        cost = calculate_cost("claude-sonnet-4-6", input_tokens=850, output_tokens=320)
        expected = (3.0 * 850 + 15.0 * 320) / 1_000_000
        assert abs(cost - expected) < 0.000001
