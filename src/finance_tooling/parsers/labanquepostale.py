"""La Banque Postale statement parser."""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal
from pathlib import Path

from finance_tooling.models import Transaction
from finance_tooling.parsers.base import (
    BaseStatementParser,
    NormalizeConfig,
    ParsedRow,
    ParserOutput,
    ValidationPayload,
)
from finance_tooling.parsers.common import parse_decimal

_DAY_MONTH_PATTERN = re.compile(r"(0[1-9]|[12][0-9]|3[01])[/\-](0[1-9]|1[012])")
_FILE_YEAR_PATTERN = re.compile(
    r"((?:19|20)\d{2})[/-]?(0[1-9]|1[012])[/-]?(0[1-9]|[12][0-9]|3[01])"
)
_TRANSACTION_ROW_PATTERN = re.compile(
    r"^\s*(?P<date>\d{2}/\d{2})\s+"
    r"(?P<description>.*?)\s+"
    r"(?P<amount>-?(?:\d{1,3}|\d{1,3}(?:(?:\.| )\d{3})+), ?\d{2})\s*$"
)
_TOTAL_PATTERN = re.compile(
    r"Total\s?des\s?op.rations\s"
    r"(-?(?:\d{1,3}|\d{1,3}(?:(?:\.|\s)\d{3})+),\s?\d{2}?)\s"
    r"(-?(?:\d{1,3}|\d{1,3}(?:(?:\.|\s)\d{3})+),\s?\d{2}?)"
)
_OPENING_BALANCE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"([+-]?\d{1,3}(?:[ .]\d{3})*,\d{2})\s*\n\s*Ancien\s+solde\s+au\s+\d{2}/\d{2}/\d{4}",
        re.IGNORECASE,
    ),
    re.compile(
        r"Ancien\s+solde\s+au\s+\d{2}/\d{2}/\d{4}\s*[+-]?\s*(\d{1,3}(?:[ .]\d{3})*,\d{2})",
        re.IGNORECASE,
    ),
)
_CLOSING_BALANCE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"Votre\s*nouveau\s*solde\s+au\s+\d{2}/\d{2}/\d{4}\s*[+-]?\s*(\d{1,3}(?:[ .]\d{3})*,\d{2})",
        re.IGNORECASE,
    ),
    re.compile(
        r"Nouveau\s*solde\s+au\s+\d{2}/\d{2}/\d{4}\s*[+-]?\s*(\d{1,3}(?:[ .]\d{3})*,\d{2})",
        re.IGNORECASE,
    ),
)
_CONTINUATION_NOISE_PREFIXES = (
    "LA BANQUE POSTALE",
    "PAGE ",
    "RELEVE N",
    "VOS OPERATIONS",
    "DATE OP",
    "DEBIT(",
    "CREDIT(",
    "VOTRE NOUVEAU SOLDE",
    "NOUVEAU SOLDE",
    "ANCIEN SOLDE",
    "SITUATION DE VOTRE CCP",
    "IBAN",
    "BIC",
    "MR ",
    "MME ",
    "SERVICE CLIENTS",
    "VIREMENT DEPUIS ",
)
_CONTINUATION_NOISE_EXACT = {
    "TOTALDESOPERATIONS",
    "TOTAL DES OPERATIONS",
}
_CONTINUATION_BOUNDARY_MARKERS = (
    "totaldesoperation",
    "totaldesoperations",
    "nouveausoldeau",
    "pourvotreinformation",
    "ilvousestconseilledeconservercereleve",
    "bonasavoir",
    "commentfaireopposition",
    "lagarantiedevosdepots",
    "serviceclients",
    "releven",
)
_PAGE_MARKER_PATTERN = re.compile(r"^\s*PAGE\s+\d+\s*/\s*\d+\s*$", re.IGNORECASE)
_CREDIT_HINTS = (
    "VIREMENT DE",
    "VIREMENT INSTANTANE DE",
    "CREDIT DU",
    "CREDIT CARTE BANCAIRE",
    "REMISE DE CHEQUES",
    "AVANTAGE CREDIT IMMOBILIER",
    "REMBOURSEMENT",
)


class LaBanquePostaleParser(BaseStatementParser):
    """Parser for La Banque Postale monthly account statements."""

    name = "labanquepostale"
    bank = "LaBanquePostale"

    def _filename_markers(self) -> tuple[str, ...]:
        return ("labanquepostale", "releve_ccp", "ccp")

    def _content_markers(self) -> tuple[str, ...]:
        return ("la banque postale", "releve de votre ccp")

    def parse(self, file_path: Path, full_text: str) -> ParserOutput:
        if _is_fee_statement(file_path=file_path, full_text=full_text):
            return ParserOutput(transactions=[], warnings=[], validation=None)
        return super().parse(file_path, full_text)

    def _extract_rows(
        self, file_path: Path, full_text: str
    ) -> tuple[list[ParsedRow], list[str], dict[str, object] | None]:
        year = self._resolve_year(file_path.name)
        rows: list[ParsedRow] = []
        lines = full_text.splitlines()

        for index, raw_line in enumerate(lines):
            match = _TRANSACTION_ROW_PATTERN.match(raw_line)
            if match is None:
                continue
            day, month = _DAY_MONTH_PATTERN.findall(match.group("date"))[0]
            details = _collect_continuation(lines=lines, start=index + 1)
            description = " ".join([match.group("description").strip(), details]).strip()
            description = _clean_lbp_description(description)
            rows.append(
                ParsedRow(
                    raw_date=f"{day}/{month}/{year}",
                    raw_description=description,
                    raw_amount=match.group("amount"),
                    raw_currency_hint="EUR",
                )
            )

        return rows, [], None

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
        del file_path, transaction_sum
        opening_balance = _extract_balance(full_text, _OPENING_BALANCE_PATTERNS)
        closing_balance = _extract_balance(full_text, _CLOSING_BALANCE_PATTERNS)
        if opening_balance is not None and closing_balance is not None:
            return ValidationPayload(
                mode="balance",
                opening_balance=opening_balance,
                closing_balance=closing_balance,
                reason="missing_opening_or_closing",
                severity="info",
            )
        return ValidationPayload(
            mode="uncheckable",
            opening_balance=opening_balance,
            closing_balance=closing_balance,
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


def _normalize_marker(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_only = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return "".join(character for character in ascii_only.lower() if character.isalnum())


def _is_fee_statement(*, file_path: Path, full_text: str) -> bool:
    marker = _normalize_marker(f"{file_path.name} {full_text}")
    return "relevedefrais" in marker


def _extract_balance(full_text: str, patterns: tuple[re.Pattern[str], ...]) -> Decimal | None:
    extracted: Decimal | None = None
    for pattern in patterns:
        for match in pattern.finditer(full_text):
            value = parse_decimal(match.group(1))
            if value is not None:
                extracted = value
    return extracted


def _collect_continuation(*, lines: list[str], start: int) -> str:
    details: list[str] = []
    for raw_line in lines[start:]:
        if _TRANSACTION_ROW_PATTERN.match(raw_line):
            break
        line = " ".join(raw_line.split())
        if not line:
            continue
        if _is_continuation_boundary(line):
            break
        if _is_continuation_noise(line):
            continue
        details.append(line)
    return " ".join(details).strip()


def _is_continuation_boundary(line: str) -> bool:
    if _PAGE_MARKER_PATTERN.match(line):
        return True
    compact_upper = "".join(line.upper().split())
    if compact_upper.startswith("TOTALDESOP"):
        return True
    marker = _normalize_marker(line)
    if not marker:
        return False
    return any(marker.startswith(prefix) for prefix in _CONTINUATION_BOUNDARY_MARKERS)


def _is_continuation_noise(line: str) -> bool:
    upper = line.upper()
    compact = upper.replace(" ", "")
    if compact in _CONTINUATION_NOISE_EXACT:
        return True
    if any(upper.startswith(prefix) for prefix in _CONTINUATION_NOISE_PREFIXES):
        return True
    return not any(character.isalpha() for character in upper)


def _clean_lbp_description(description: str) -> str:
    cleaned = description.strip()
    cleaned = re.sub(
        r"\bVIREMENT\s+DEPUIS\s+LA\s+BANQUE\s+POSTALE\b.*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(
        r"^\d+(?=(AVANTAGE|COTISATION|COMMISSION|FOURNITURE)\b)",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned
