"""Payment tool stubs. Swap in Razorpay / your CRM here."""

from __future__ import annotations

import logging
from datetime import datetime

from services.pii import mask_text

logger = logging.getLogger(__name__)


# A real payment API (Razorpay etc.) takes the idempotency key, so a retried request returns the
# first link instead of creating a second one. The stub keeps the same contract.
_seen: dict[str, dict] = {}


async def create_payment_request(customer_name: str, amount: int, send_to_number: str = "",
                                 idempotency_key: str = "") -> dict:
    if idempotency_key in _seen:
        return _seen[idempotency_key]
    logger.info("[payment] link | %s | ₹%s | to=%s", customer_name, amount, mask_text(send_to_number) or "registered number")
    result = {
        "status": "sent",
        "customer_name": customer_name,
        "amount": amount,
        "send_to_number": send_to_number or None,
        "payment_link": f"https://pay.example.com/stub/{customer_name.lower().replace(' ', '-')}-{amount}",
        "created_at": datetime.now().isoformat(),
        "idempotency_key": idempotency_key,
    }
    if idempotency_key:
        _seen[idempotency_key] = result
    return result


async def log_payment_promise(customer_name: str, promised_date: str, amount: int, reason: str = "",
                              idempotency_key: str = "") -> dict:
    logger.info("[payment] promise | %s | %s | ₹%s | %s", customer_name, promised_date, amount, reason)
    return {"status": "promise_logged", "customer_name": customer_name, "promised_date": promised_date,
            "amount": amount, "reason": reason, "idempotency_key": idempotency_key}
