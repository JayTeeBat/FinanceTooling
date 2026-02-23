from datetime import date
from decimal import Decimal
from pathlib import Path

from finance_tooling.classify import classify_transactions
from finance_tooling.models import Transaction


def test_classify_transactions_assigns_keyword_category() -> None:
    tx = Transaction(
        booking_date=date(2026, 2, 1),
        description="CARD PAYMENT UBER TRIP",
        amount_native=Decimal("-17.50"),
        currency="USD",
        source_file=Path("stmt.pdf"),
        bank="Revolut",
        parser="revolut",
    )

    classified = classify_transactions([tx])

    assert classified[0].category == "Transport"
    assert classified[0].amount_native == Decimal("-17.50")
