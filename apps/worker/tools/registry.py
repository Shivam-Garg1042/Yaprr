"""Tool catalog. The API validates agent configs against the same names
(apps/api/yaprr_api/schemas.py: TOOL_CATALOG); each agent enables a subset."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from livekit.agents import RunContext, function_tool

from tools import payment
from tools.readback import ReadBackGate, caller_turns

logger = logging.getLogger(__name__)

EventSink = Callable[[str, dict[str, Any]], None]


def build_tools(names: list[str], *, customer_name: str, context: dict[str, str], emit: EventSink,
                call_key: str = "") -> list:
    """Return LiveKit function tools for the enabled names, bound to this call.

    Tools that write something real (promise-to-pay, payment link) go through a read-back
    gate (tools/readback.py) and carry an idempotency key, so a retry never acts twice."""
    gate = ReadBackGate()

    async def gated(ctx: RunContext, action: str, facts: dict, run) -> str:
        state, msg = gate.check(action, facts, caller_turns(ctx.session))
        if state == "confirm":
            emit("readback_requested", {"action": action, **facts})
            return msg
        if state == "done":
            emit("duplicate_action_skipped", {"action": action, **facts})
            return msg + " (Already done earlier in this call; don't do it again.)"
        result = await run(f"{call_key}:{gate.key(action, facts)}")
        gate.record(action, facts, result)
        return result

    @function_tool
    async def hangup(ctx: RunContext):
        """End the call. Use after the customer acknowledges your closing line, or on voicemail/abuse."""
        emit("call_hangup_requested", {})
        await ctx.session.aclose()
        return "Call ended."

    @function_tool
    async def transfer_to_human(ctx: RunContext, reason: str):
        """Escalate to a human agent. Give a short reason."""
        emit("transfer_to_human", {"reason": reason})
        return f"Escalation logged: {reason}. Tell the customer a team member will call them back."

    @function_tool
    async def log_complaint(ctx: RunContext, complaint_type: str, details: str):
        """Record a complaint, hardship or follow-up note. complaint_type e.g. battery_issue, financial_hardship."""
        emit("complaint_logged", {"complaint_type": complaint_type, "details": details})
        return f"Complaint logged: {complaint_type}"

    @function_tool
    async def log_payment_promise(ctx: RunContext, promised_date: str, amount: int, reason: str = ""):
        """Record a promise-to-pay once the customer commits to a specific date and amount.
        The first call asks you to read the date and amount back; call again after they confirm."""
        async def run(idem: str) -> str:
            result = await payment.log_payment_promise(customer_name, promised_date, amount, reason, idempotency_key=idem)
            emit("payment_promise_logged", result)
            return f"Promise logged for {promised_date}."
        return await gated(ctx, "log_payment_promise", {"promised_date": promised_date, "amount": amount}, run)

    @function_tool
    async def create_payment_request(ctx: RunContext, amount: int, send_to_number: str = ""):
        """Create a payment link and send it by SMS. send_to_number: only if the customer gave a different
        number (e.g. a family member's smartphone). Never read the link aloud.
        The first call asks you to read the amount (and number) back; call again after they confirm."""
        async def run(idem: str) -> str:
            result = await payment.create_payment_request(customer_name, amount, send_to_number, idempotency_key=idem)
            emit("payment_request_created", result)
            return "Payment link sent by SMS."
        facts = {"amount": amount} | ({"send_to_number": send_to_number} if send_to_number else {})
        return await gated(ctx, "create_payment_request", facts, run)

    available = {f.__name__: f for f in (hangup, transfer_to_human, log_complaint, log_payment_promise,
                                         create_payment_request)}
    unknown = [n for n in names if n not in available]
    if unknown:
        logger.warning("[yaprr] agent enables unknown tools %s; ignoring", unknown)
    return [available[n] for n in names if n in available]
