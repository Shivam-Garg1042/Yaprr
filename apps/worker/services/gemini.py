"""Gemini model helpers.

Gemini 2.x and 3.x take different "thinking" settings:
  - 2.x: thinking_budget (int tokens; 0 = off, -1 = dynamic)
  - 3.x: thinking_level ("minimal" | "low" | "medium" | "high"); budget is rejected
Keeping this in one place means switching models is a pure `.env` change.
"""

from __future__ import annotations


def is_gemini_3_or_newer(model: str) -> bool:
    name = model.removeprefix("models/")
    if not name.startswith("gemini-"):
        return False
    try:
        return int(name.split("-")[1].split(".")[0]) >= 3
    except (IndexError, ValueError):
        return False


def thinking_config_for(model: str, *, level: str = "minimal", budget: int = 0) -> dict:
    """Fastest sensible thinking setting for the given model, as a plain dict."""
    if is_gemini_3_or_newer(model):
        return {"thinking_level": level}
    return {"thinking_budget": budget}
