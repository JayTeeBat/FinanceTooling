"""La Banque Postale statement parser."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from finance_tooling.models import Transaction
from finance_tooling.parsers.base import (
    BaseStatementParser,
    NormalizeConfig,
    ParsedRow,
    ValidationPayload,
)
from finance_tooling.parsers.common import parse_decimal

_DAY_MONTH_PATTERN = re.compile(r"(0[1-9]|[12][0-9]|3[01])[/\-](0[1-9]|1[012])")
_FILE_YEAR_PATTERN = re.compile(
    r"((?:19|20)\d{2})[/-]?(0[1-9]|1[012])[/-]?(0[1-9]|[12][0-9]|3[01])"
)
_TRANSACTION_PATTERN = re.compile(
    r"\n\s*(\d{2}/\d{2})\s+"
    r"([^\n]*?)\s"
    r"(-?(?:\d{1,3}|\d{1,3}(?:(?:\.| )\d{3})+), ?\d{2}?)"
    r"(?:\n((?!\s*\d{2}/\d{2}).*))?"
)
_TOTAL_PATTERN = re.compile(
    r"Total\s?des\s?op.rations\s"
    r"(-?(?:\d{1,3}|\d{1,3}(?:(?:\.|\s)\d{3})+),\s?\d{2}?)\s"
    r"(-?(?:\d{1,3}|\d{1,3}(?:(?:\.|\s)\d{3})+),\s?\d{2}?)"
)
_CREDIT_HINTS = (
    "VIREMENT DE",
    "VIREMENT INSTANTANE DE",
    "CREDIT DU",
    "CREDIT CARTE BANCAIRE",
    "REMISE DE CHEQUES",
    "AVANTAGE CREDIT IMMOBILIER",
)


class LaBanquePostaleParser(BaseStatementParser):
    """Parser for La Banque Postale monthly account statements."""

    name = "labanquepostale"
    bank = "LaBanquePostale"

    def can_handle(self, file_path: Path, first_page_text: str) -> bool:
        marker = f"{file_path.name} {first_page_text}".lower()
        return (
            "labanquepostale" in marker
            or "la banque postale" in marker
            or "releve_ccp" in marker
            or "releve de votre ccp" in marker
        )

    def _extract_rows(self, file_path: Path, full_text: str) -> tuple[list[ParsedRow], list[str]]:
        year = self._resolve_year(file_path.name)
        rows: list[ParsedRow] = []

        matches = _TRANSACTION_PATTERN.findall(f"\n{full_text}")
        for match in matches:
            day, month = _DAY_MONTH_PATTERN.findall(match[0])[0]
            details = match[3] if len(match) > 3 else ""
            description = " ".join([match[1].strip(), details.strip()]).strip()
            rows.append(
                ParsedRow(
                    raw_date=f"{day}/{month}/{year}",
                    raw_description=description,
                    raw_amount=match[2],
                    raw_currency_hint="EUR",
                )
            )

        return rows, []

    def _normalize_config(self) -> NormalizeConfig:
        return NormalizeConfig(
            sign_mode="debit_default_with_positive_hints",
            default_currency="EUR",
            positive_hints=_CREDIT_HINTS,
            description_fallback="Unknown transaction",
        )

    def _build_validation_payload(
        self,
        file_path: Path,
        full_text: str,
        transaction_sum: Decimal,
    ) -> ValidationPayload:
        del file_path, full_text, transaction_sum
        return ValidationPayload(
            mode="uncheckable",
            opening_balance=None,
            closing_balance=None,
            reason="missing_opening_or_closing",
            severity="info",
        )

    def _post_normalization_warnings(
        self,
        file_path: Path,
        full_text: str,
        transactions: list[Transaction],
    ) -> list[str]:
        transaction_sum = sum((tx.amount_native for tx in transactions), start=Decimal("0"))
        warnings: list[str] = []
        total_matches = _TOTAL_PATTERN.findall(full_text)
        if total_matches and transactions:
            debit = parse_decimal(total_matches[-1][0])
            credit = parse_decimal(total_matches[-1][1])
            if debit is not None and credit is not None:
                expected = -debit + credit
                if transaction_sum != expected:
                    warnings.append(
                        f"{file_path.name}: totals mismatch expected {expected} "
                        f"but parsed {transaction_sum}"
                    )
        return warnings

    @staticmethod
    def _resolve_year(filename: str) -> int:
        matches = _FILE_YEAR_PATTERN.findall(filename)
        if matches:
            return int(matches[0][0])
        return date.today().year
