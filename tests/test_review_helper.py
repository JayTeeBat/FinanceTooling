from __future__ import annotations

from pathlib import Path

import pandas as pd

from finance_tooling.reporting.review_helper import render_review_helper_html


def test_render_review_helper_html_embeds_expected_controls(tmp_path: Path) -> None:
    destination = tmp_path / "review_helper.html"
    review_rows = pd.DataFrame(
        [
            {
                "transaction_id": "tx_1",
                "booking_date": "2026-01-01",
                "description": "Merchant Alpha",
                "amount_native": -10.0,
                "bank": "REVOLUT",
                "review_group_key": "merchant alpha | REVOLUT | Main",
                "review_group_size": 2,
                "original_category": "Uncategorized",
                "original_subcategory": None,
                "category": "Uncategorized",
                "subcategory": None,
                "review_status": "todo",
                "project_tags": None,
                "review_comment": None,
            }
        ]
    )

    render_review_helper_html(review_rows, destination)
    html = destination.read_text(encoding="utf-8")

    assert destination.exists()
    assert "Review Helper" in html
    assert "Download draft JSON" in html
    assert "transactions_review.json" in html
    assert 'data-column-key="booking_date"' in html
    assert "sort-indicator" in html
    assert 'data-column-key="bank"' in html
    assert "filter-menu" in html
