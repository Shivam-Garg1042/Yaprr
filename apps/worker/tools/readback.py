"""Read-back before acting, enforced in code.

A wrong date or amount in a promise-to-pay is worse than none: the collections
team follows up on the wrong day, or the customer gets a link for the wrong amount.
A prompt rule ("confirm before saving") is easy for an LLM to skip, so the tool
itself refuses to act on the first call:

  1st call  log_payment_promise("15 Nov", 4200)
            -> NOT saved. "Read this back and ask them to confirm, then call again."
  agent     "Toh main note kar rahi hoon: pandrah November, chaar hazaar do sau. Sahi hai?"
  caller    "haan"
  2nd call  same values, AND the caller has spoken since -> saved.

Changed values (the caller corrected the date) start a new read-back.
The same action with the same values is done at most once per call, so a
retried or repeated tool call can't log a promise or send a link twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _norm(v: Any) -> str:
    return " ".join(str(v).lower().split())


@dataclass
class ReadBackGate:
    pending: dict[str, tuple[tuple, int]] = field(default_factory=dict)  # action -> (facts, caller turns seen)
    done: dict[str, str] = field(default_factory=dict)  # idempotency key -> result already returned

    @staticmethod
    def key(action: str, facts: dict[str, Any]) -> str:
        return action + "|" + "|".join(f"{k}={_norm(v)}" for k, v in sorted(facts.items()))

    def check(self, action: str, facts: dict[str, Any], caller_turns: int) -> tuple[str, str | None]:
        """Returns ("run", None) when the action may run now, ("done", result) when it already
        ran with these values, or ("confirm", instructions) when the agent must read back first."""
        k = self.key(action, facts)
        if k in self.done:
            return "done", self.done[k]
        sig = tuple(sorted((name, _norm(v)) for name, v in facts.items()))
        prev = self.pending.get(action)
        if prev and prev[0] == sig and caller_turns > prev[1]:
            del self.pending[action]
            return "run", None
        self.pending[action] = (sig, caller_turns)
        said = ", ".join(f"{name.replace('_', ' ')}: {v}" for name, v in facts.items())
        return "confirm", (
            f"NOT done yet. First read these back to the caller in one short sentence and ask if they are correct "
            f"({said}). Say numbers and dates as words. If they confirm, call {action} again with exactly the same "
            f"values. If they correct something, call it with the corrected values."
        )

    def record(self, action: str, facts: dict[str, Any], result: str) -> None:
        self.done[self.key(action, facts)] = result


def caller_turns(session: Any) -> int:
    """How many times the caller has spoken so far (user messages in the chat history)."""
    try:
        return sum(1 for item in session.history.items if getattr(item, "role", None) == "user")
    except Exception:  # noqa: BLE001 - never block a call on bookkeeping
        return 0
