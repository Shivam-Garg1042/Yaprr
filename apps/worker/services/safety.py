"""Call guardrails that don't depend on the LLM behaving.

Prompt rules ("hang up on voicemail", "be polite") can fail; these can't:
  1. Max call duration: a hard timer ends the call politely.
  2. Inactivity: if caller and agent are both silent for `user_away_timeout`,
     nudge "hello?" up to N times, then hang up. Resets when the caller speaks.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from services.config import SafetySettings

logger = logging.getLogger(__name__)


class CallGuard:
    def __init__(self, session: Any, settings: SafetySettings, on_event: Callable[[str, dict], None]):
        self.session = session
        self.settings = settings
        self.on_event = on_event
        self.inactivity_prompts = 0
        self.end_reason: str | None = None
        self._timer: asyncio.Task | None = None
        self._ending = False

    # ── lifecycle ────────────────────────────────────────────────────────────
    def start(self) -> None:
        self.session.on("user_state_changed", self._on_user_state)
        if self.settings.max_call_seconds > 0:
            self._timer = asyncio.create_task(self._max_duration_timer(), name="max_call_duration")

    def stop(self) -> None:
        if self._timer and not self._timer.done():
            self._timer.cancel()

    # ── handlers ─────────────────────────────────────────────────────────────
    def _on_user_state(self, ev: Any) -> None:
        if ev.new_state == "speaking":
            self.inactivity_prompts = 0
            return
        if ev.new_state != "away" or self._ending:
            return
        if self.inactivity_prompts >= self.settings.max_inactivity_prompts:
            asyncio.create_task(self.end_call("inactivity"))
            return
        self.inactivity_prompts += 1
        self.on_event("inactivity_prompt", {"attempt": self.inactivity_prompts})
        try:
            self.session.say(self.settings.inactivity_message)
        except RuntimeError:  # session already closing
            pass

    async def _max_duration_timer(self) -> None:
        await asyncio.sleep(self.settings.max_call_seconds)
        await self.end_call("max_duration")

    async def end_call(self, reason: str) -> None:
        if self._ending:
            return
        self._ending = True
        self.end_reason = reason
        logger.info("[yaprr] CallGuard ending call: %s", reason)
        self.on_event("call_guard_end", {"reason": reason})
        try:
            handle = self.session.say(self.settings.closing_message, allow_interruptions=False)
            await asyncio.wait_for(handle.wait_for_playout(), timeout=10)
        except Exception:  # noqa: BLE001 - best effort goodbye, never block hangup
            pass
        await self.session.aclose()
