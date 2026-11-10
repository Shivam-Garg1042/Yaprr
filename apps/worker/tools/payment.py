"""Payment tool stubs. Swap in Razorpay / your CRM here."""

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


async def create_payment_request(customer_name: str, amount: int, send_to_number: str = "") -> dict:
    logger.info("[payment] link | %s | ₹%s | to=%s", customer_name, amount, send_to_number or "registered number")
    return {
        "status": "sent",
        "customer_name": customer_name,
        "amount": amount,
        "send_to_number": send_to_number or None,
        "payment_link": f"https://pay.example.com/stub/{customer_name.lower().replace(' ', '-')}-{amount}",
        "created_at": datetime.now().isoformat(),
    }


async def log_payment_promise(customer_name: str, promised_date: str, amount: int, reason: str = "") -> dict:
    logger.info("[payment] promise | %s | %s | ₹%s | %s", customer_name, promised_date, amount, reason)
    return {"status": "promise_logged", "customer_name": customer_name, "promised_date": promised_date,
            "amount": amount, "reason": reason}
