import json
from pathlib import Path
from typing import TypedDict

import pytest

from finance_tooling.parsers.boursobank import BoursobankParser
from finance_tooling.parsers.generic import GenericParser
from finance_tooling.parsers.hsbc import HsbcParser
from finance_tooling.parsers.labanquepostale import LaBanquePostaleParser
from finance_tooling.parsers.revolut import RevolutParser

_CASES_PATH = Path(__file__).parent / "fixtures" / "parser_samples" / "synthetic_cases.json"


class _ParserCase(TypedDict):
    name: str
    parser: str
    file_name: str
    input_text: str
    expected_transaction_count: int
    expected_validation_status: str
    expected_positive_count: int
    expected_negative_count: int


def _load_cases() -> list[_ParserCase]:
    raw = json.loads(_CASES_PATH.read_text(encoding="utf-8"))
    return [_ParserCase(**case) for case in raw]


def _parser_by_name(name: str):
    parsers = {
        "generic": GenericParser(),
        "hsbc": HsbcParser(),
        "labanquepostale": LaBanquePostaleParser(),
        "boursobank": BoursobankParser(),
        "revolut": RevolutParser(),
    }
    return parsers[name]


@pytest.mark.parametrize("case", _load_cases(), ids=lambda case: str(case["name"]))
def test_parser_conformance(case: _ParserCase) -> None:
    parser_name = case["parser"]
    parser = _parser_by_name(parser_name)

    result = parser.parse(
        Path(case["file_name"]),
        case["input_text"],
    )

    assert len(result.transactions) == case["expected_transaction_count"]
    assert result.validation is not None
    assert result.validation.status == case["expected_validation_status"]

    positives = sum(1 for tx in result.transactions if tx.amount_native > 0)
    negatives = sum(1 for tx in result.transactions if tx.amount_native < 0)

    assert positives == case["expected_positive_count"]
    assert negatives == case["expected_negative_count"]
