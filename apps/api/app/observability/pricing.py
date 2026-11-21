"""Versioned model pricing for estimated API cost accounting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

# Versioned catalog. Historical rows store pricing_version; never rewrite past costs.
PRICING_CATALOG_VERSION = "2026-11-21.1"
PRICING_CURRENCY = "USD"
PRICING_SOURCE = "https://openai.com/api/pricing (operator-maintained snapshot)"

# Rates are USD per 1M tokens. Cached input uses cached rate when reported.
_CATALOG: dict[str, dict[str, Any]] = {
    "gpt-4o-mini": {
        "input_per_million": Decimal("0.15"),
        "cached_input_per_million": Decimal("0.075"),
        "output_per_million": Decimal("0.60"),
        "effective_date": date(2025, 1, 1),
    },
    "gpt-4o": {
        "input_per_million": Decimal("2.50"),
        "cached_input_per_million": Decimal("1.25"),
        "output_per_million": Decimal("10.00"),
        "effective_date": date(2025, 1, 1),
    },
}


@dataclass(frozen=True, slots=True)
class ModelPrice:
    model: str
    pricing_version: str
    currency: str
    input_per_million: Decimal
    cached_input_per_million: Decimal | None
    output_per_million: Decimal
    effective_date: date
    source: str


@dataclass(frozen=True, slots=True)
class CostEstimate:
    """Estimated API cost from reported tokens x catalog rates (not billing totals)."""

    amount: Decimal | None
    currency: str
    pricing_version: str | None
    available: bool
    label: str


def lookup_price(model: str, *, at: date | None = None) -> ModelPrice | None:
    entry = _CATALOG.get(model)
    if entry is None:
        # Strip date suffixes like gpt-4o-mini-2024-07-18
        for key, value in _CATALOG.items():
            if model.startswith(key):
                entry = value
                model = key
                break
    if entry is None:
        return None
    effective = entry["effective_date"]
    if at is not None and at < effective:
        return None
    return ModelPrice(
        model=model,
        pricing_version=PRICING_CATALOG_VERSION,
        currency=PRICING_CURRENCY,
        input_per_million=entry["input_per_million"],
        cached_input_per_million=entry.get("cached_input_per_million"),
        output_per_million=entry["output_per_million"],
        effective_date=effective,
        source=PRICING_SOURCE,
    )


def estimate_cost(
    *,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    cached_input_tokens: int | None,
) -> CostEstimate:
    """Estimate cost from actual token counts. Missing usage → unavailable."""
    if input_tokens is None or output_tokens is None:
        return CostEstimate(
            amount=None,
            currency=PRICING_CURRENCY,
            pricing_version=None,
            available=False,
            label="unavailable (token usage unknown)",
        )
    price = lookup_price(model)
    if price is None:
        return CostEstimate(
            amount=None,
            currency=PRICING_CURRENCY,
            pricing_version=None,
            available=False,
            label="unavailable (model price unknown)",
        )

    cached = cached_input_tokens or 0
    if cached < 0:
        cached = 0
    # Cached tokens are a subset of input — bill non-cached input + cached at cached rate.
    billable_input = max(input_tokens - cached, 0)
    million = Decimal("1000000")
    cost = (Decimal(billable_input) / million) * price.input_per_million
    if cached and price.cached_input_per_million is not None:
        cost += (Decimal(cached) / million) * price.cached_input_per_million
    elif cached:
        # No cached rate — count cached tokens at standard input rate (already in input).
        pass
    cost += (Decimal(output_tokens) / million) * price.output_per_million
    # Quantize to 8 decimal places for storage stability.
    amount = cost.quantize(Decimal("0.00000001"))
    return CostEstimate(
        amount=amount,
        currency=price.currency,
        pricing_version=price.pricing_version,
        available=True,
        label="estimate (not official provider billing)",
    )


def catalog_entries() -> list[ModelPrice]:
    return [lookup_price(m) for m in _CATALOG if lookup_price(m) is not None]  # type: ignore[misc]
