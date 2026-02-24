from datetime import date
from decimal import Decimal
from pathlib import Path

from finance_tooling.models import Transaction
from finance_tooling.parsers.base import BaseStatementParser, ValidationPayload


class _DummyParser(BaseStatementParser):
    name = "dummy"
    bank = "Dummy"

    def __init__(self, payload: ValidationPayload) -> None:
        self._payload = payload

    def can_handle(self, file_path: Path, first_page_text: str) -> bool:
        del file_path, first_page_text
        return True

    def _parse_transactions(
        self, file_path: Path, full_text: str
    ) -> tuple[list[Transaction], list[str]]:
        del full_text
        return (
            [
                Transaction(
                    booking_date=date(2024, 1, 2),
                    description="tx",
                    amount_native=Decimal("-10.00"),
                    currency="EUR",
                    source_file=file_path,
                    bank=self.bank,
                    parser=self.name,
                )
            ],
            [],
        )

    def _build_validation_payload(
        self,
        file_path: Path,
        full_text: str,
        transaction_sum: Decimal,
    ) -> ValidationPayload:
        del file_path, full_text, transaction_sum
        return self._payload


def test_base_parser_builds_pass_validation() -> None:
    parser = _DummyParser(
        ValidationPayload(
            mode="balance",
            opening_balance=Decimal("100.00"),
            closing_balance=Decimal("90.00"),
            reason="missing_opening_or_closing",
            severity="info",
        )
    )

    result = parser.parse(Path("dummy.pdf"), "irrelevant")

    assert result.validation is not None
    assert result.validation.status == "pass"
    assert result.validation.severity == "none"
    assert result.warnings == []


def test_base_parser_builds_fail_validation_with_warning() -> None:
    parser = _DummyParser(
        ValidationPayload(
            mode="balance",
            opening_balance=Decimal("100.00"),
            closing_balance=Decimal("89.00"),
            reason="missing_opening_or_closing",
            severity="info",
        )
    )

    result = parser.parse(Path("dummy.pdf"), "irrelevant")

    assert result.validation is not None
    assert result.validation.status == "fail"
    assert result.validation.reason == "balance_mismatch"
    assert result.validation.severity == "warning"
    assert len(result.warnings) == 1


def test_base_parser_builds_uncheckable_when_balances_missing() -> None:
    parser = _DummyParser(
        ValidationPayload(
            mode="balance",
            opening_balance=Decimal("100.00"),
            closing_balance=None,
            reason="missing_opening_or_closing",
            severity="info",
        )
    )

    result = parser.parse(Path("dummy.pdf"), "irrelevant")

    assert result.validation is not None
    assert result.validation.status == "uncheckable"
    assert result.validation.reason == "missing_opening_or_closing"
    assert result.validation.severity == "info"
    assert result.warnings == []


def test_base_parser_supports_explicit_uncheckable_mode() -> None:
    parser = _DummyParser(
        ValidationPayload(
            mode="uncheckable",
            opening_balance=None,
            closing_balance=None,
            reason="unsupported_parser",
            severity="info",
        )
    )

    result = parser.parse(Path("dummy.pdf"), "irrelevant")

    assert result.validation is not None
    assert result.validation.status == "uncheckable"
    assert result.validation.reason == "unsupported_parser"
