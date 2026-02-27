"""Parser interfaces and helper dataclasses."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol

from finance_tooling.models import Transaction
from finance_tooling.parsers.common import normalize_row_to_transaction


@dataclass(frozen=True)
class ParserOutput:
    """Result of parsing a single statement file."""

    transactions: list[Transaction]
    warnings: list[str]
    validation: StatementValidation | None = None
    diagnostics: dict[str, object] | None = None


@dataclass(frozen=True)
class StatementValidation:
    """Per-file statement reconciliation metadata."""

    source_file: Path
    bank: str
    parser: str
    statement_type: str
    opening_balance: Decimal | None
    closing_balance: Decimal | None
    transaction_sum: Decimal
    expected_closing_balance: Decimal | None
    difference: Decimal | None
    status: str
    reason: str | None
    severity: str


class StatementParser(Protocol):
    """Protocol implemented by bank statement parsers."""

    name: str
    bank: str

    def match_score(self, file_path: Path, first_page_text: str) -> int: ...

    def parse(self, file_path: Path, full_text: str) -> ParserOutput: ...


@dataclass(frozen=True)
class ParsedRow:
    """Raw row extracted by a parser before shared normalization."""

    raw_date: str
    raw_description: str
    raw_amount: str
    raw_currency_hint: str | None = None


@dataclass(frozen=True)
class NormalizeConfig:
    """Parser-specific normalization policy knobs."""

    sign_mode: Literal[
        "explicit_sign",
        "debit_default_with_positive_hints",
        "positive_default_with_negative_hints",
        "hint_priority_with_default_debit",
    ]
    default_currency: str
    positive_hints: tuple[str, ...] = ()
    negative_hints: tuple[str, ...] = ()
    description_fallback: str = "Unknown transaction"


@dataclass(frozen=True)
class ValidationPayload:
    """Parser-provided inputs for statement validation construction."""

    mode: Literal["balance", "uncheckable"]
    opening_balance: Decimal | None
    closing_balance: Decimal | None
    reason: str | None = None
    severity: str = "info"


class BaseStatementParser(ABC):
    """Template parser base that centralizes parse output and validation flow."""

    name: str
    bank: str

    def match_score(self, file_path: Path, first_page_text: str) -> int:
        marker_filename = file_path.name.lower()
        marker_content = first_page_text.lower()
        marker_all = f"{marker_filename} {marker_content}"

        score = 0
        score += 3 * sum(
            1 for marker in self._filename_markers() if marker.lower() in marker_filename
        )
        score += 2 * sum(
            1 for marker in self._content_markers() if marker.lower() in marker_content
        )
        score -= 4 * sum(1 for marker in self._negative_markers() if marker.lower() in marker_all)
        return score

    def parse(self, file_path: Path, full_text: str) -> ParserOutput:
        rows, warnings, diagnostics = self._extract_rows(file_path, full_text)
        config = self._normalize_config()

        transactions: list[Transaction] = []
        for row in rows:
            transaction = normalize_row_to_transaction(
                row=row,
                file_path=file_path,
                bank=self.bank,
                parser_name=self.name,
                config=config,
            )
            if transaction is not None:
                transactions.append(transaction)

        warnings.extend(self._post_normalization_warnings(file_path, full_text, transactions))

        transaction_sum = sum((tx.amount_native for tx in transactions), start=Decimal("0"))
        payload = self._build_validation_payload(file_path, full_text, transaction_sum)

        validation_warning: str | None = None
        if payload.mode == "balance":
            validation, validation_warning = self._validation_from_opening_closing(
                file_path=file_path,
                opening_balance=payload.opening_balance,
                closing_balance=payload.closing_balance,
                transaction_sum=transaction_sum,
                missing_reason=payload.reason or "missing_opening_or_closing",
                missing_severity=payload.severity,
            )
        else:
            validation = self._validation_uncheckable(
                file_path=file_path,
                transaction_sum=transaction_sum,
                opening_balance=payload.opening_balance,
                closing_balance=payload.closing_balance,
                reason=payload.reason or "unknown",
                severity=payload.severity,
            )

        if validation_warning is not None:
            warnings.append(validation_warning)
        return ParserOutput(
            transactions=transactions,
            warnings=warnings,
            validation=validation,
            diagnostics=diagnostics,
        )

    @abstractmethod
    def _extract_rows(
        self, file_path: Path, full_text: str
    ) -> tuple[list[ParsedRow], list[str], dict[str, object] | None]:
        """Extract raw statement rows and parser warnings from input text."""

    @abstractmethod
    def _normalize_config(self) -> NormalizeConfig:
        """Return parser-specific normalization config for row -> transaction conversion."""

    @abstractmethod
    def _build_validation_payload(
        self,
        file_path: Path,
        full_text: str,
        transaction_sum: Decimal,
    ) -> ValidationPayload:
        """Build validation payload for shared reconciliation construction."""

    def _post_normalization_warnings(
        self,
        file_path: Path,
        full_text: str,
        transactions: list[Transaction],
    ) -> list[str]:
        del file_path, full_text, transactions
        return []

    def _filename_markers(self) -> tuple[str, ...]:
        return ()

    def _content_markers(self) -> tuple[str, ...]:
        return ()

    def _negative_markers(self) -> tuple[str, ...]:
        return ()

    def _validation_uncheckable(
        self,
        *,
        file_path: Path,
        transaction_sum: Decimal,
        opening_balance: Decimal | None,
        closing_balance: Decimal | None,
        reason: str,
        severity: str,
    ) -> StatementValidation:
        return StatementValidation(
            source_file=file_path,
            bank=self.bank,
            parser=self.name,
            statement_type="statement",
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            transaction_sum=transaction_sum,
            expected_closing_balance=None,
            difference=None,
            status="uncheckable",
            reason=reason,
            severity=severity,
        )

    def _validation_from_opening_closing(
        self,
        *,
        file_path: Path,
        opening_balance: Decimal | None,
        closing_balance: Decimal | None,
        transaction_sum: Decimal,
        missing_reason: str,
        missing_severity: str,
    ) -> tuple[StatementValidation, str | None]:
        if opening_balance is None or closing_balance is None:
            return (
                self._validation_uncheckable(
                    file_path=file_path,
                    transaction_sum=transaction_sum,
                    opening_balance=opening_balance,
                    closing_balance=closing_balance,
                    reason=missing_reason,
                    severity=missing_severity,
                ),
                None,
            )

        expected = opening_balance + transaction_sum
        difference = expected - closing_balance
        if abs(difference) <= Decimal("0.01"):
            return (
                StatementValidation(
                    source_file=file_path,
                    bank=self.bank,
                    parser=self.name,
                    statement_type="statement",
                    opening_balance=opening_balance,
                    closing_balance=closing_balance,
                    transaction_sum=transaction_sum,
                    expected_closing_balance=expected,
                    difference=difference,
                    status="pass",
                    reason=None,
                    severity="none",
                ),
                None,
            )

        return (
            StatementValidation(
                source_file=file_path,
                bank=self.bank,
                parser=self.name,
                statement_type="statement",
                opening_balance=opening_balance,
                closing_balance=closing_balance,
                transaction_sum=transaction_sum,
                expected_closing_balance=expected,
                difference=difference,
                status="fail",
                reason="balance_mismatch",
                severity="warning",
            ),
            self._validation_warning_message(
                file_path=file_path,
                opening_balance=opening_balance,
                transaction_sum=transaction_sum,
                expected_closing_balance=expected,
                closing_balance=closing_balance,
                difference=difference,
            ),
        )

    def _validation_warning_message(
        self,
        *,
        file_path: Path,
        opening_balance: Decimal,
        transaction_sum: Decimal,
        expected_closing_balance: Decimal,
        closing_balance: Decimal,
        difference: Decimal,
    ) -> str:
        return (
            f"{file_path.name}: reconciliation mismatch opening {opening_balance} + "
            f"transactions {transaction_sum} = {expected_closing_balance} but closing is "
            f"{closing_balance} (diff {difference})"
        )
