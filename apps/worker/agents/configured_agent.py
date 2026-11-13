"""One Agent class for every agent: everything comes from the DB config."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from livekit.agents import Agent

from agents.voice_rules import VOICE_RULES
from tools.registry import EventSink, build_tools


class _KeepMissing(defaultdict):
    """str.format_map helper: unknown {vars} stay as-is instead of raising."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render(template: str, context: dict[str, str]) -> str:
    return template.format_map(_KeepMissing(str, context)) if template else ""


class ConfiguredAgent(Agent):
    def __init__(self, config: dict[str, Any], context: dict[str, str], emit: EventSink, call_key: str = ""):
        ctx = {"persona_name": config.get("persona_name", ""), **context}
        self.opening_line = render(config.get("opening_line", ""), ctx)
        instructions = (
            VOICE_RULES.format(language=config.get("language", "Hinglish"))
            + "\n"
            + render(config["prompt"], ctx)
        )
        tools = build_tools(config.get("tools", []), customer_name=ctx.get("customer_name", "customer"),
                            context=ctx, emit=emit, call_key=call_key)
        super().__init__(instructions=instructions, tools=tools)

    async def on_enter(self) -> None:
        """Outbound call: the agent speaks first. A fixed opening line goes straight to
        TTS (no LLM round-trip, ~100 ms to first audio)."""
        if self.opening_line:
            self.session.say(self.opening_line)
        else:
            self.session.generate_reply(instructions="Greet the customer and start the call.")
