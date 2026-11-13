"""Mask personal data before anything is stored or logged.

The live call is NOT masked: the agent needs a real number to send a payment
link to a family member. Masking applies to what we keep: the call record sent
to the API (transcripts are public in the demo), local JSON files, and logs.

What counts as PII here (Indian lending calls):
- phone numbers: 98765 43210, +91-9876543210, 09876543210
- Aadhaar (12 digits), card numbers (13-19 digits), bank account numbers (9-18 digits)
- PAN (ABCDE1234F), email addresses, UPI IDs (name@okhdfc)
- numbers spoken as digit words, which is how STT often writes them:
  "nine eight seven six five four...", "नौ आठ सात छह पाँच चार..."

What stays: amounts (₹4,200, "चार हज़ार दो सौ"), dates, short numbers. A run of
digits is masked only when it's long enough to identify someone.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")
_UPI = re.compile(r"\b[\w.-]{2,}@[a-zA-Z]{2,}\b")
_PAN = re.compile(r"\b[A-Za-z]{5}\d{4}[A-Za-z]\b")
# Digit groups of 3+ separated by one space or dash ("98765 43210", "1234-5678-9012").
# Requiring 3+ per group keeps "pay 2000 on 15 11" from turning into one long number.
_DIGIT_RUN = re.compile(r"(?<![\w+])(?:\+?91[ -])?\d{3,}(?:[ -]\d{3,})*(?![\w])")

_DIGIT_WORDS = {
    # English
    "zero", "oh", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    # Hindi in Devanagari, with common STT spellings
    "शून्य", "ज़ीरो", "जीरो", "एक", "दो", "तीन", "चार", "पांच", "पाँच", "छह", "छः", "छे", "सात", "आठ", "नौ",
    # Hindi in Roman script
    "ek", "do", "teen", "char", "chaar", "paanch", "panch", "chhe", "chah", "saat", "aath", "nau",
}
_SPOKEN_MIN = 6  # six digits in a row is an ID, not an amount ("चार हज़ार दो सौ" has non-digit words)


def _classify(digits: str) -> str | None:
    n = len(digits)
    if (n == 10 and digits[0] in "6789") or (n == 12 and digits.startswith("91") and digits[2] in "6789") \
            or (n == 11 and digits.startswith("0") and digits[1] in "6789"):
        return "PHONE"
    if n == 12:
        return "AADHAAR"
    if 13 <= n <= 19 and _luhn(digits):
        return "CARD"
    if 9 <= n <= 19:
        return "ACCOUNT"
    return None


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch) * (2 if i % 2 else 1)
        total += d - 9 if d > 9 else d
    return total % 10 == 0


def _mask_spoken_digits(text: str, found: Counter) -> str:
    tokens = re.split(r"(\s+)", text)  # keep whitespace so the text reads the same
    out: list[str] = []
    run: list[str] = []

    def flush() -> None:
        words = [t for t in run if not t.isspace()]
        if len(words) >= _SPOKEN_MIN:
            found["SPOKEN_NUMBER"] += 1
            trailing = run[-1] if run and run[-1].isspace() else ""
            out.append("[NUMBER]" + trailing)
        else:
            out.extend(run)
        run.clear()

    for tok in tokens:
        word = tok.strip(",.।?!").lower()
        if tok.isspace() and run:
            run.append(tok)
        elif word in _DIGIT_WORDS:
            run.append(tok)
        else:
            flush()
            out.append(tok)
    flush()
    return "".join(out)


def mask_text(text: str, found: Counter | None = None) -> str:
    """Return `text` with PII replaced by [PHONE], [PAN], ... `found` counts what was masked."""
    if not text:
        return text
    found = found if found is not None else Counter()
    text = text.translate(_DEVANAGARI_DIGITS)

    def sub(pattern: re.Pattern, label: str, s: str) -> str:
        def repl(_m: re.Match) -> str:
            found[label] += 1
            return f"[{label}]"
        return pattern.sub(repl, s)

    text = sub(_EMAIL, "EMAIL", text)
    text = sub(_UPI, "UPI", text)
    text = sub(_PAN, "PAN", text)

    def digits(m: re.Match) -> str:
        label = _classify(re.sub(r"\D", "", m.group()))
        if not label:
            return m.group()
        found[label] += 1
        return f"[{label}]"

    text = _DIGIT_RUN.sub(digits, text)
    return _mask_spoken_digits(text, found)


def mask_value(value: Any, found: Counter | None = None) -> Any:
    """Mask every string inside dicts/lists (call records, event payloads)."""
    found = found if found is not None else Counter()
    if isinstance(value, str):
        return mask_text(value, found)
    if isinstance(value, dict):
        return {k: mask_value(v, found) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask_value(v, found) for v in value]
    return value
