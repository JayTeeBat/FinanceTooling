import json
from decimal import Decimal
from pathlib import Path
from typing import TypedDict, cast

import pytest

from finance_tooling.parsers.revolut import RevolutParser

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "revolut"
_CASES_PATH = _FIXTURE_ROOT / "cases.json"


class _RevolutFixtureCase(TypedDict):
    id: str
    description: str
    file_name: str
    text_file: str
    expected_transaction_amounts: list[str]
    expected_transaction_count: int
    expected_transaction_sum: str
    expected_opening_balance: str | None
    expected_closing_balance: str | None
    expected_validation_status: str
    expected_validation_severity: str
    expected_validation_reason: str | None
    expected_difference: str | None
    expected_warning_substrings: list[str]


def _parse_decimal_or_none(raw_value: str | None) -> Decimal | None:
    if raw_value is None:
        return None
    return Decimal(raw_value)


def _load_cases() -> list[_RevolutFixtureCase]:
    raw = json.loads(_CASES_PATH.read_text(encoding="utf-8"))
    return [cast(_RevolutFixtureCase, case) for case in raw]


def test_revolut_fixture_manifest_is_valid() -> None:
    cases = _load_cases()
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))
    for case in cases:
        fixture_path = _FIXTURE_ROOT / case["text_file"]
        assert fixture_path.exists(), f"Missing Revolut fixture text file: {fixture_path}"


@pytest.mark.parametrize("case", _load_cases(), ids=lambda case: case["id"])
def test_revolut_parser_fixture_regression(case: _RevolutFixtureCase) -> None:
    parser = RevolutParser()
    fixture_path = _FIXTURE_ROOT / case["text_file"]
    text = fixture_path.read_text(encoding="utf-8")

    result = parser.parse(Path(case["file_name"]), text)
    validation = result.validation

    assert validation is not None
    assert len(result.transactions) == case["expected_transaction_count"]

    amounts = [tx.amount_native for tx in result.transactions]
    expected_amounts = [Decimal(raw_amount) for raw_amount in case["expected_transaction_amounts"]]
    assert amounts == expected_amounts

    expected_transaction_sum = Decimal(case["expected_transaction_sum"])
    transaction_sum = sum((tx.amount_native for tx in result.transactions), start=Decimal("0"))
    assert transaction_sum == expected_transaction_sum
    assert validation.transaction_sum == expected_transaction_sum

    expected_opening = _parse_decimal_or_none(case["expected_opening_balance"])
    expected_closing = _parse_decimal_or_none(case["expected_closing_balance"])
    expected_difference = _parse_decimal_or_none(case["expected_difference"])

    assert validation.opening_balance == expected_opening
    assert validation.closing_balance == expected_closing
    assert validation.status == case["expected_validation_status"]
    assert validation.severity == case["expected_validation_severity"]
    assert validation.reason == case["expected_validation_reason"]
    assert validation.difference == expected_difference

    if expected_opening is None or expected_closing is None:
        assert validation.expected_closing_balance is None
    else:
        assert validation.expected_closing_balance == (expected_opening + expected_transaction_sum)

    expected_warning_substrings = case["expected_warning_substrings"]
    assert len(result.warnings) == len(expected_warning_substrings)
    for snippet in expected_warning_substrings:
        assert any(snippet in warning for warning in result.warnings)
