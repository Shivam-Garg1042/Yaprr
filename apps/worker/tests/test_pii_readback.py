import asyncio
from collections import Counter
from types import SimpleNamespace

from services.pii import mask_text, mask_value
from tools.readback import ReadBackGate, caller_turns


def test_masks_indian_pii_but_not_amounts_or_dates():
    assert mask_text("mera number 98765 43210 hai") == "mera number [PHONE] hai"
    assert mask_text("+91-9876543210 pe bhejo") == "[PHONE] pe bhejo"
    assert mask_text("नंबर ९८७६५४३२१० है") == "नंबर [PHONE] है"
    assert mask_text("PAN ABCDE1234F, aadhaar 1234 5678 9012") == "PAN [PAN], aadhaar [AADHAAR]"
    assert mask_text("card 4111 1111 1111 1111") == "card [CARD]"
    assert mask_text("account 123456789012345 hai") == "account [ACCOUNT] hai"
    assert mask_text("upi shivam@okhdfc, mail a.b@gmail.com") == "upi [UPI], mail [EMAIL]"
    assert mask_text("मेरा नंबर नौ आठ सात छह पाँच चार तीन दो एक शून्य है") == "मेरा नंबर [NUMBER] है"
    keep = "EMI चार हज़ार दो सौ, ₹4,200 on 15 11 2026, pay 2000 on 15, loan VL-2024-0042, do you have one two minutes?"
    assert mask_text(keep) == keep


def test_mask_value_walks_records_and_counts():
    found = Counter()
    rec = mask_value({"transcript": [{"text": "9876543210"}], "n": 5, "args": ['{"send_to_number": "9876543210"}']}, found)
    assert rec["transcript"][0]["text"] == "[PHONE]" and "[PHONE]" in rec["args"][0] and rec["n"] == 5
    assert found["PHONE"] == 2


def test_readback_needs_a_caller_turn_and_same_values():
    g = ReadBackGate()
    facts = {"promised_date": "15 Nov", "amount": 4200}
    assert g.check("log_payment_promise", facts, caller_turns=3)[0] == "confirm"
    assert g.check("log_payment_promise", facts, caller_turns=3)[0] == "confirm"  # caller hasn't spoken yet
    assert g.check("log_payment_promise", {**facts, "promised_date": "16 Nov"}, caller_turns=4)[0] == "confirm"  # corrected
    assert g.check("log_payment_promise", {**facts, "promised_date": "16 nov"}, caller_turns=5) == ("run", None)
    g.record("log_payment_promise", {**facts, "promised_date": "16 Nov"}, "Promise logged.")
    state, msg = g.check("log_payment_promise", {**facts, "promised_date": "16 Nov"}, caller_turns=6)
    assert state == "done" and msg == "Promise logged."  # idempotent: never logged twice


def test_caller_turns_counts_user_messages():
    s = SimpleNamespace(history=SimpleNamespace(items=[SimpleNamespace(role="assistant"), SimpleNamespace(role="user"),
                                                       SimpleNamespace(type="function_call"), SimpleNamespace(role="user")]))
    assert caller_turns(s) == 2 and caller_turns(object()) == 0


def test_payment_stub_is_idempotent():
    from tools import payment
    a = asyncio.run(payment.create_payment_request("Ramesh", 4200, idempotency_key="room1:k"))
    b = asyncio.run(payment.create_payment_request("Ramesh", 4200, idempotency_key="room1:k"))
    assert a is b
