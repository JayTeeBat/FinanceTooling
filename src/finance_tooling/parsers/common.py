"""Common parser helpers."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

DATE_PATTERNS = (
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%Y-%m-%d",
    "%d/%m/%y",
    "%d-%m-%y",
    "%d %b %Y",
    "%d %b %y",
)

CURRENCY_REGEX = re.compile(r"\b(USD|EUR|LBP|GBP|JPY|CHF|CAD|AUD|AED|SAR|QAR|KWD|BHD|OMR)\b")
SYMBOL_TO_CURRENCY = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}


def parse_date(raw_date: str) -> date | None:
    for pattern in DATE_PATTERNS:
        try:
            return datetime.strptime(raw_date, pattern).date()
        except ValueError:
            continue
    return None


def parse_decimal(raw_amount: str) -> Decimal | None:
    token = raw_amount.strip().replace(" ", "")
    negative = token.startswith("-") or token.endswith("-") or ("(" in token and ")" in token)
    token = token.strip("()-+")

    if token.count(",") and token.count("."):
        if token.rfind(",") > token.rfind("."):
            token = token.replace(".", "")
            token = token.replace(",", ".")
        else:
            token = token.replace(",", "")
    elif token.count(","):
        decimal_slice = token.rsplit(",", maxsplit=1)[-1]
        if decimal_slice.isdigit() and len(decimal_slice) <= 2:
            token = token.replace(",", ".")
        else:
            token = token.replace(",", "")

    try:
        value = Decimal(token)
    except InvalidOperation:
        return None
    return -value if negative else value


def detect_currency(text: str) -> str:
    code_match = CURRENCY_REGEX.search(text)
    if code_match:
        return code_match.group(1)
    for symbol, currency in SYMBOL_TO_CURRENCY.items():
        if symbol in text:
            return currency
    return "UNKNOWN"
