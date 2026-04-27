from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPrice:
    input_per_million: float
    cached_input_per_million: float | None
    output_per_million: float


# Standard OpenAI API pricing observed on April 25, 2026.
MODEL_PRICES: dict[str, ModelPrice] = {
    "gpt-5.5": ModelPrice(5.00, 0.50, 30.00),
    "gpt-5.4": ModelPrice(2.50, 0.25, 15.00),
    "gpt-5.4-mini": ModelPrice(0.75, 0.075, 4.50),
    "gpt-5.3-codex": ModelPrice(1.75, 0.175, 14.00),
    "gpt-5.2-codex": ModelPrice(1.75, 0.175, 14.00),
    "gpt-5.1-codex": ModelPrice(1.25, 0.125, 10.00),
    "gpt-5.1-codex-max": ModelPrice(1.25, 0.125, 10.00),
    "gpt-5-codex": ModelPrice(1.25, 0.125, 10.00),
    "gpt-5.2": ModelPrice(1.75, 0.175, 14.00),
    "gpt-5.1": ModelPrice(1.25, 0.125, 10.00),
    "gpt-5": ModelPrice(1.25, 0.125, 10.00),
    "gpt-5-mini": ModelPrice(0.25, 0.025, 2.00),
    "gpt-5-nano": ModelPrice(0.05, 0.005, 0.40),
}


def normalize_model(model: str | None) -> str | None:
    if not model:
        return None
    value = model.strip().lower()
    aliases = {
        "gpt-5.4 mini": "gpt-5.4-mini",
        "gpt-5.4-mini": "gpt-5.4-mini",
        "gpt-5.3-codex": "gpt-5.3-codex",
        "codex-auto-review": None,
    }
    return aliases.get(value, value)


def estimate_cost(
    model: str | None,
    input_tokens: int,
    cache_hit_tokens: int,
    output_tokens: int,
) -> tuple[float | None, bool]:
    normalized = normalize_model(model)
    if not normalized or normalized not in MODEL_PRICES:
        return None, False
    price = MODEL_PRICES[normalized]
    uncached_input = max(input_tokens - cache_hit_tokens, 0)
    cached_rate = price.cached_input_per_million
    if cached_rate is None and cache_hit_tokens:
        return None, False
    cost = (
        uncached_input * price.input_per_million
        + cache_hit_tokens * (cached_rate or 0)
        + output_tokens * price.output_per_million
    ) / 1_000_000
    return round(cost, 8), True
