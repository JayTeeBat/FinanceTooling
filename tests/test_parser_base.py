from decimal import Decimal
from pathlib import Path

from finance_tooling.parsers.base import (
    BaseStatementParser,
    NormalizeConfig,
    ParsedRow,
    ValidationPayload,
)
from finance_tooling.parsers.common import infer_signed_amount, normalize_row_to_transaction


class _DummyParser(BaseStatementParser):
    name = "dummy"
    bank = "Dummy"

    def __init__(self, payload: ValidationPayload) -> None:
        self._payload = payload

    def _extract_rows(self, file_path: Path, full_text: str) -> tuple[list[ParsedRow], list[str]]:
        del full_text
        return (
            [
                ParsedRow(
                    raw_date="02/01/2024",
                    raw_description="tx",
                    raw_amount="10.00",
                    raw_currency_hint="EUR",
                )
            ],
            [],
        )

    def _normalize_config(self) -> NormalizeConfig:
        return NormalizeConfig(
            sign_mode="explicit_sign",
            default_currency="EUR",
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
            closing_balance=Decimal("110.00"),
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
            closing_balance=Decimal("109.00"),
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


def test_infer_signed_amount_debit_default_positive_hints() -> None:
    assert infer_signed_amount(
        Decimal("10.00"),
        description="salary transfer",
        mode="debit_default_with_positive_hints",
        positive_hints=("SALARY",),
        negative_hints=(),
    ) == Decimal("10.00")
    assert infer_signed_amount(
        Decimal("10.00"),
        description="card payment",
        mode="debit_default_with_positive_hints",
        positive_hints=("SALARY",),
        negative_hints=(),
    ) == Decimal("-10.00")


def test_infer_signed_amount_hint_priority_default_debit_mode() -> None:
    assert infer_signed_amount(
        Decimal("10.00"),
        description="payment from employer",
        mode="hint_priority_with_default_debit",
        positive_hints=("PAYMENT FROM",),
        negative_hints=("TO ",),
    ) == Decimal("10.00")
    assert infer_signed_amount(
        Decimal("10.00"),
        description="transfer to john",
        mode="hint_priority_with_default_debit",
        positive_hints=("PAYMENT FROM",),
        negative_hints=("TO ",),
    ) == Decimal("-10.00")
    assert infer_signed_amount(
        Decimal("10.00"),
        description="neutral description",
        mode="hint_priority_with_default_debit",
        positive_hints=("PAYMENT FROM",),
        negative_hints=("TO ",),
    ) == Decimal("-10.00")


def test_normalize_row_to_transaction_uses_defaults() -> None:
    tx = normalize_row_to_transaction(
        row=ParsedRow(
            raw_date="02/01/2024",
            raw_description="  ",
            raw_amount="1,200.50",
            raw_currency_hint=None,
        ),
        file_path=Path("dummy.pdf"),
        bank="Dummy",
        parser_name="dummy",
        config=NormalizeConfig(
            sign_mode="explicit_sign",
            default_currency="EUR",
            description_fallback="Unknown transaction",
        ),
    )

    assert tx is not None
    assert tx.description == "Unknown transaction"
    assert tx.currency == "EUR"
    assert tx.amount_native == Decimal("1200.50")


class _MarkerParser(_DummyParser):
    def _filename_markers(self) -> tuple[str, ...]:
        return ("alpha",)

    def _content_markers(self) -> tuple[str, ...]:
        return ("beta",)

    def _negative_markers(self) -> tuple[str, ...]:
        return ("forbidden",)


def test_base_parser_match_score_counts_marker_hits() -> None:
    parser = _MarkerParser(
        ValidationPayload(
            mode="uncheckable",
            opening_balance=None,
            closing_balance=None,
        )
    )

    score = parser.match_score(Path("alpha_statement.pdf"), "beta marker")
    assert score == 5


def test_base_parser_match_score_applies_negative_penalty() -> None:
    parser = _MarkerParser(
        ValidationPayload(
            mode="uncheckable",
            opening_balance=None,
            closing_balance=None,
        )
    )

    score = parser.match_score(Path("alpha_statement.pdf"), "beta marker forbidden")
    assert score == 1
