from decimal import Decimal
from pathlib import Path

from finance_tooling.parsers.boursobank import BoursobankParser
from finance_tooling.parsers.hsbc import HsbcParser
from finance_tooling.parsers.labanquepostale import LaBanquePostaleParser
from finance_tooling.parsers.registry import select_parser, select_parser_with_diagnostics
from finance_tooling.parsers.revolut import RevolutParser


def test_labanquepostale_parser_extracts_rows() -> None:
    parser = LaBanquePostaleParser()
    text = """
    25/11 CREDIT CARTE BANCAIRE 4,00
    26/11 VIREMENT DE EMPLOYEUR 1 200,00
    27/11 ACHAT CB SUPERMARCHE 42,00
    Total des operations 4,00 1 200,00
    """

    result = parser.parse(Path("releve_CCP1126215Y027_20241224.pdf"), text)

    assert len(result.transactions) == 3
    assert result.transactions[0].amount_native > 0
    assert result.transactions[1].amount_native > 0
    assert result.transactions[2].amount_native < 0
    assert result.validation is not None
    assert result.validation.status == "uncheckable"


def test_labanquepostale_parser_builds_balance_validation_when_balances_present() -> None:
    parser = LaBanquePostaleParser()
    text = """
    Votre nouveau solde au 24/12/2024 + 1 200,00
    Vos operations
    Date Operation Debit Credit
    800,00
    Ancien solde au 22/11/2024
    25/11 CREDIT CARTE BANCAIRE 50,00
    26/11 ACHAT CB SUPERMARCHE 20,00
    Nouveau solde au 24/12/2024 830,00
    """

    result = parser.parse(Path("releve_CCP1126215Y027_20241224.pdf"), text)

    assert len(result.transactions) == 2
    assert result.validation is not None
    assert result.validation.status == "pass"
    assert result.validation.opening_balance == Decimal("800.00")
    assert result.validation.closing_balance == Decimal("830.00")


def test_labanquepostale_parser_captures_multiline_continuations() -> None:
    parser = LaBanquePostaleParser()
    text = """
    25/09 VIREMENT INSTANTANE A                           400,00
         PHILIPPE PENICAUT SUPERB Thomazo Location Fev 24
    27/09 ACHAT CB AJC-ISM 26.09.23                       17,80
         EUR 17,80 CARTE NO 885 SAMSUNG PAY
    """

    result = parser.parse(Path("releve_CCP1126215Y027_20241224.pdf"), text)

    assert len(result.transactions) == 2
    assert "PHILIPPE PENICAUT SUPERB" in result.transactions[0].description
    assert "EUR 17,80 CARTE NO 885 SAMSUNG PAY" in result.transactions[1].description


def test_labanquepostale_parser_excludes_fee_statements_from_reconciliation() -> None:
    parser = LaBanquePostaleParser()
    text = """
    Relevé de frais
    Periode Du 01/01/2024 au 31/12/2024
    Total des frais payes 279,94
    """

    result = parser.parse(Path("LaBanquePostale Jacques Relevé de frais_20250102.pdf"), text)

    assert result.transactions == []
    assert result.validation is None


def test_labanquepostale_parser_marks_remboursement_as_credit() -> None:
    parser = LaBanquePostaleParser()
    text = """
    20/01 4REMBOURSEMENT DE LA COTISATION FORMULE DE COMPTE 63,90
    """

    result = parser.parse(Path("releve_CCP1126215Y027_20250124.pdf"), text)

    assert len(result.transactions) == 1
    assert result.transactions[0].amount_native == Decimal("63.90")


def test_labanquepostale_parser_keeps_virement_a_negative() -> None:
    parser = LaBanquePostaleParser()
    text = """
    12/06 VIREMENT INSTANTANE A BOURSORAMA JACQUES Virement depuis La Banque Postale 200,00
    """

    result = parser.parse(Path("releve_CCP1126215Y027_20250624.pdf"), text)

    assert len(result.transactions) == 1
    assert result.transactions[0].amount_native == Decimal("-200.00")


def test_registry_selects_lbp_parser() -> None:
    parser = select_parser(
        Path("LaBanquePostale Jacques releve_CCP1126215Y027_20241224.pdf"),
        "Releve de votre CCP",
    )

    assert parser.name == "labanquepostale"


def test_registry_prefers_revolut_when_text_mentions_boursorama() -> None:
    parser = select_parser(
        Path("Revolut Jacques EUR account-statement_2023-01-01_2023-12-31_en-gb.pdf"),
        "Revolut Ltd ... Reference: Virement interne depuis BOURSORAMA BANQUE ...",
    )

    assert parser.name == "revolut"


def test_registry_uses_stable_order_for_score_ties() -> None:
    parser = select_parser(
        Path("combined_hsbc_boursorama_statement.pdf"),
        "HSBC and Boursorama markers both present",
    )

    assert parser.name == "boursobank"


def test_registry_falls_back_to_generic_when_no_parser_matches_threshold() -> None:
    parser = select_parser(
        Path("misc_document.pdf"),
        "Completely unrelated content with no bank markers",
    )

    assert parser.name == "generic"


def test_registry_returns_diagnostics_payload() -> None:
    selection = select_parser_with_diagnostics(
        Path("Revolut account-statement_2023.pdf"),
        "Revolut account-statement",
    )

    assert selection.parser.name == "revolut"
    assert selection.score >= selection.threshold
    assert len(selection.candidates) >= 2
    assert selection.candidates[0].parser_name == "revolut"


def test_revolut_parser_parses_currency_symbol_amounts() -> None:
    parser = RevolutParser()
    text = """
    Account transactions from 1 January 2019 to 31 December 2019
    19 Jun 2019 PayPlug €4.90 €95.10
    24 Jun 2019 Payment from JeanBaptiste Thomazo €20.00 €115.10
    """

    result = parser.parse(Path("account-statement_2019.pdf"), text)

    assert len(result.transactions) == 2
    assert result.transactions[0].amount_native == Decimal("-4.90")
    assert result.transactions[1].amount_native == Decimal("20.00")


def test_hsbc_parser_parses_compact_date_rows() -> None:
    parser = HsbcParser()
    text = """
    02Mar16 DD AIL-HSBC 6.87 4,953.91
    03Mar16 SALARY COMPANY LTD 1,500.00 6,453.91
    """

    result = parser.parse(Path("HSBC_2016_statement.pdf"), text)

    assert len(result.transactions) == 2
    assert result.transactions[0].amount_native < 0
    assert result.transactions[1].amount_native > 0


def test_boursobank_parser_parses_lines_without_space_after_date() -> None:
    parser = BoursobankParser()
    text = """
    17/09/2020VIR INST JACQUES THOMAZO 17/09/2020 800,00
    """

    result = parser.parse(Path("Releve-compte-30-09-2020.pdf"), text)

    assert len(result.transactions) == 1
    assert result.transactions[0].amount_native > 0


def test_hsbc_parser_emits_warning_for_reconciliation_mismatch() -> None:
    parser = HsbcParser()
    text = """
    Opening Balance 100.00
    02 Mar 2024 CARD SHOP 10.00 90.00
    Closing Balance 91.00
    """

    result = parser.parse(Path("HSBC_2024_statement.pdf"), text)

    assert result.validation is not None
    assert result.validation.status == "fail"
    assert result.validation.severity == "warning"
    assert len(result.warnings) == 1


def test_hsbc_parser_marks_uncheckable_as_info_when_balances_missing() -> None:
    parser = HsbcParser()
    text = """
    02 Mar 2024 CARD SHOP 10.00 90.00
    """

    result = parser.parse(Path("HSBC_2024_statement.pdf"), text)

    assert result.validation is not None
    assert result.validation.status == "uncheckable"
    assert result.validation.severity == "info"
    assert result.warnings == []


def test_hsbc_parser_supports_balance_brought_forward_markers() -> None:
    parser = HsbcParser()
    text = """
    Balance Brought Forward 100.00
    02 Mar 2024 CARD SHOP 10.00 90.00
    Balance Carried Forward 90.00
    """

    result = parser.parse(Path("HSBC_2024_statement.pdf"), text)

    assert result.validation is not None
    assert result.validation.status == "pass"
    assert result.validation.severity == "none"


def test_hsbc_parser_supports_multiline_descriptions() -> None:
    parser = HsbcParser()
    text = """
    Opening Balance 200.00
    02 Mar 2024 CARD PAYMENT RETAILER
    LONDON 10.00 190.00
    Closing Balance 190.00
    """

    result = parser.parse(Path("HSBC_2024_statement.pdf"), text)

    assert len(result.transactions) == 1
    assert "RETAILER LONDON" in result.transactions[0].description
    assert result.validation is not None
    assert result.validation.status == "pass"


def test_hsbc_parser_respects_cr_dr_markers_for_sign_inference() -> None:
    parser = HsbcParser()
    text = """
    Opening Balance 100.00
    02 Mar 2024 CASH WITHDRAWAL 5.00DR 95.00
    03 Mar 2024 MISC ENTRY 10.00CR 105.00
    Closing Balance 105.00
    """

    result = parser.parse(Path("HSBC_2024_statement.pdf"), text)

    assert len(result.transactions) == 2
    assert result.transactions[0].amount_native == Decimal("-5.00")
    assert result.transactions[1].amount_native == Decimal("10.00")
    assert result.validation is not None
    assert result.validation.status == "pass"


def test_hsbc_parser_warns_when_balances_exist_but_no_rows_parsed() -> None:
    parser = HsbcParser()
    text = """
    Opening Balance 100.00
    Some section with no transaction rows
    Closing Balance 100.00
    """

    result = parser.parse(Path("HSBC_2024_statement.pdf"), text)

    assert result.validation is not None
    assert result.validation.status == "pass"
    assert len(result.transactions) == 0
    assert len(result.warnings) == 1


def test_hsbc_parser_parses_multiple_continuation_transactions_in_single_date_block() -> None:
    parser = HsbcParser()
    text = """
    Opening Balance 1000.00
    27 Nov 19 CR MARS CHOCOLATE UK 156.96
    VIS LONDON BOROUGH OF
    LONDON W6 9JU 4.00
    VIS BRITISH GAS ONLINE
    BRITISHGAS.CO 198.51
    Closing Balance 954.45
    """

    result = parser.parse(Path("HSBC_2019_statement.pdf"), text)

    assert [tx.amount_native for tx in result.transactions] == [
        Decimal("156.96"),
        Decimal("-4.00"),
        Decimal("-198.51"),
    ]
    assert result.validation is not None
    assert result.validation.status == "pass"


def test_hsbc_parser_does_not_apply_cr_header_marker_to_bp_continuation_rows() -> None:
    parser = HsbcParser()
    text = """
    Opening Balance 1000.00
    01 Mar 2024 CR REVERSAL OF 25-08
    BP MERCHANT PAYMENT 100.00 900.00
    Closing Balance 900.00
    """

    result = parser.parse(Path("HSBC_2024_statement.pdf"), text)

    assert len(result.transactions) == 1
    assert result.transactions[0].amount_native == Decimal("-100.00")
    assert result.validation is not None
    assert result.validation.status == "pass"


def test_hsbc_parser_ignores_amount_noise_after_block_transaction_rows() -> None:
    parser = HsbcParser()
    text = """
    Opening Balance 100.00
    02 Mar 2024 VIS RETAILER NAME
    LONDON 10.00 90.00
    Interest rates information variable balance and cap details 19.90
    Closing Balance 90.00
    """

    result = parser.parse(Path("HSBC_2024_statement.pdf"), text)

    assert len(result.transactions) == 1
    assert result.transactions[0].amount_native == Decimal("-10.00")
    assert result.validation is not None
    assert result.validation.status == "pass"


def test_hsbc_parser_inherits_header_cr_marker_for_non_prefixed_continuation_amount() -> None:
    parser = HsbcParser()
    text = """
    Opening Balance 100.00
    02 Mar 2024 CR PAYMENT REVERSAL
    MERCHANT CREDIT 10.00 110.00
    Closing Balance 110.00
    """

    result = parser.parse(Path("HSBC_2024_statement.pdf"), text)

    assert len(result.transactions) == 1
    assert result.transactions[0].amount_native == Decimal("10.00")
    assert result.validation is not None
    assert result.validation.status == "pass"
