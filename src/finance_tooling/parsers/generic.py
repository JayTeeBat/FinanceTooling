"""Generic fallback parser for unknown statement layouts."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from finance_tooling.parsers.base import (
    BaseStatementParser,
    NormalizeConfig,
    ParsedRow,
    ValidationPayload,
)

_DATE_REGEX = re.compile(r"\b(\d{1,4}[/-]\d{1,2}[/-]\d{2,4})\b")
_AMOUNT_REGEX = re.compile(r"[-+]?\(?\d[\d,.\s]*\d(?:[.,]\d{1,2})?\)?-?")


class GenericParser(BaseStatementParser):
    """Regex-based fallback parser."""

    name = "generic"
    bank = "Unknown"

    def match_score(self, file_path: Path, first_page_text: str) -> int:
        del file_path, first_page_text
        return 0

    def _extract_rows(
        self, file_path: Path, full_text: str
    ) -> tuple[list[ParsedRow], list[str], dict[str, object] | None]:
        del file_path
        rows: list[ParsedRow] = []

        for raw_line in full_text.splitlines():
            line = " ".join(raw_line.split())
            if not line:
                continue

            date_match = _DATE_REGEX.search(line)
            if not date_match:
                continue

            amount_matches = list(_AMOUNT_REGEX.finditer(line))
            if not amount_matches:
                continue
            amount_token = amount_matches[-1].group(0)

            description = line.replace(date_match.group(0), "", 1)
            description = description.replace(amount_token, "", 1)

            rows.append(
                ParsedRow(
                    raw_date=date_match.group(1),
                    raw_description=description,
                    raw_amount=amount_token,
                    raw_currency_hint=line,
                )
            )

        return rows, [], None

    def _normalize_config(self) -> NormalizeConfig:
        return NormalizeConfig(
            sign_mode="explicit_sign",
            default_currency="UNKNOWN",
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
            reason="unsupported_parser",
            severity="info",
        )
