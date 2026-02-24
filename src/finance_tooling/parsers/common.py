"""Common parser helpers."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING

from finance_tooling.models import Transaction

if TYPE_CHECKING:
    from finance_tooling.parsers.base import NormalizeConfig, ParsedRow

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


def clean_description(raw_description: str, *, fallback: str) -> str:
    normalized = " ".join(raw_description.split()).strip(" -:\t")
    return normalized or fallback


def infer_signed_amount(
    amount: Decimal,
    *,
    description: str,
    mode: str,
    positive_hints: tuple[str, ...],
    negative_hints: tuple[str, ...],
) -> Decimal:
    if mode == "explicit_sign":
        return amount

    description_upper = description.upper()
    if mode == "debit_default_with_positive_hints":
        signed = -abs(amount)
        if any(hint in description_upper for hint in positive_hints):
            signed = abs(amount)
        return signed

    if mode == "positive_default_with_negative_hints":
        signed = abs(amount)
        if any(hint in description_upper for hint in negative_hints):
            signed = -abs(amount)
        return signed

    return amount


def normalize_row_to_transaction(
    *,
    row: ParsedRow,
    file_path: Path,
    bank: str,
    parser_name: str,
    config: NormalizeConfig,
) -> Transaction | None:
    booking_date = parse_date(row.raw_date)
    if booking_date is None:
        return None

    amount = parse_decimal(row.raw_amount)
    if amount is None:
        return None

    description = clean_description(row.raw_description, fallback=config.description_fallback)
    signed_amount = infer_signed_amount(
        amount,
        description=description,
        mode=config.sign_mode,
        positive_hints=config.positive_hints,
        negative_hints=config.negative_hints,
    )

    currency_hint = row.raw_currency_hint or row.raw_amount
    currency = detect_currency(currency_hint)
    if currency == "UNKNOWN":
        currency = config.default_currency

    return Transaction(
        booking_date=booking_date,
        description=description,
        amount_native=signed_amount,
        currency=currency,
        source_file=file_path,
        bank=bank,
        parser=parser_name,
    )
