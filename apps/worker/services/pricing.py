"""Per-model LLM prices, so the cost estimate follows whichever model an agent uses.

USD per 1M tokens (input, output). Public list prices, checked 2026-11-05;
update when providers change them. Models not listed fall back to the
PRICE_LLM_* env values in services/config.py.
"""

from __future__ import annotations

import dataclasses

from services.config import AppConfig, Pricing

LLM_PRICES_USD_PER_M: dict[str, tuple[float, float]] = {
    "qwen/qwen3.8-27b": (0.80, 4.00),  # Groq
    "gemini-2.5-flash": (0.30, 2.50),
}


def pricing_for(config: AppConfig) -> Pricing:
    prices = LLM_PRICES_USD_PER_M.get(config.llm_model)
    if not prices:
        return config.pricing
    return dataclasses.replace(config.pricing, llm_usd_per_m_input=prices[0], llm_usd_per_m_output=prices[1])
