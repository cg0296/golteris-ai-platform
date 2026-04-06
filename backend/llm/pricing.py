"""
backend/llm/pricing.py — Per-model cost-per-token lookup.

Used by client.py to calculate the cost of each LLM call in USD.
Cost must match the provider's actual bill within 1% (NFR-OB-1).

Prices are in USD per token (not per 1K or 1M tokens) for simpler math.
Update this file when providers change pricing.

Sources:
    Anthropic: https://docs.anthropic.com/en/docs/about-claude/models
    OpenAI: https://platform.openai.com/docs/models
"""

from dataclasses import dataclass


@dataclass
class ModelPricing:
    """
    Cost per token for a specific model.

    Attributes:
        input_cost_per_token: USD cost per input token
        output_cost_per_token: USD cost per output token
    """
    input_cost_per_token: float
    output_cost_per_token: float


# ---------------------------------------------------------------------------
# Pricing table — update when providers change prices
#
# Format: "model_id" → ModelPricing(input, output)
# Prices are per-token in USD (divide provider's per-million price by 1,000,000)
# ---------------------------------------------------------------------------

MODEL_PRICING: dict[str, ModelPricing] = {
    # --- Anthropic Claude ---
    # Claude Opus 4.6: $15/M input, $75/M output
    "claude-opus-4-6": ModelPricing(
        input_cost_per_token=15.0 / 1_000_000,
        output_cost_per_token=75.0 / 1_000_000,
    ),
    # Claude Sonnet 4.6: $3/M input, $15/M output
    "claude-sonnet-4-6": ModelPricing(
        input_cost_per_token=3.0 / 1_000_000,
        output_cost_per_token=15.0 / 1_000_000,
    ),
    # Claude Haiku 4.5: $0.80/M input, $4/M output
    "claude-haiku-4-5-20251001": ModelPricing(
        input_cost_per_token=0.80 / 1_000_000,
        output_cost_per_token=4.0 / 1_000_000,
    ),

    # --- OpenAI GPT ---
    # GPT-4o: $2.50/M input, $10/M output
    "gpt-4o": ModelPricing(
        input_cost_per_token=2.50 / 1_000_000,
        output_cost_per_token=10.0 / 1_000_000,
    ),
    # GPT-4.1: $2/M input, $8/M output
    "gpt-4.1": ModelPricing(
        input_cost_per_token=2.0 / 1_000_000,
        output_cost_per_token=8.0 / 1_000_000,
    ),
    # GPT-4.1-mini: $0.40/M input, $1.60/M output
    "gpt-4.1-mini": ModelPricing(
        input_cost_per_token=0.40 / 1_000_000,
        output_cost_per_token=1.60 / 1_000_000,
    ),
    # GPT-4.1-nano: $0.10/M input, $0.40/M output
    "gpt-4.1-nano": ModelPricing(
        input_cost_per_token=0.10 / 1_000_000,
        output_cost_per_token=0.40 / 1_000_000,
    ),
}


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """
    Calculate the cost of an LLM call in USD.

    Args:
        model: The model identifier (must be in MODEL_PRICING)
        input_tokens: Number of input tokens consumed
        output_tokens: Number of output tokens generated

    Returns:
        Cost in USD as a float (e.g., 0.00435)

    Raises:
        KeyError: If the model is not in the pricing table. This is intentional —
                  we want to fail loudly if an unknown model is used, rather than
                  silently logging $0.00 costs that would make the cost caps useless.
    """
    if model not in MODEL_PRICING:
        raise KeyError(
            f"Model '{model}' not found in pricing table. "
            f"Add it to backend/llm/pricing.py before using it. "
            f"Known models: {', '.join(sorted(MODEL_PRICING.keys()))}"
        )

    pricing = MODEL_PRICING[model]
    return (
        input_tokens * pricing.input_cost_per_token
        + output_tokens * pricing.output_cost_per_token
    )
