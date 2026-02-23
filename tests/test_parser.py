from decimal import Decimal
from pathlib import Path

from finance_tooling.parsers.boursobank import BoursobankParser
from finance_tooling.parsers.hsbc import HsbcParser
from finance_tooling.parsers.labanquepostale import LaBanquePostaleParser
from finance_tooling.parsers.registry import select_parser
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


def test_revolut_parser_parses_currency_symbol_amounts() -> None:
    parser = RevolutParser()
    text = """
    19 Jun 2019 PayPlug €4.90 €4.90
    24 Nov 2019 International Transfer to JeanBaptiste Thomazo €90.00 €0.45
    """

    result = parser.parse(Path("account-statement_2019.pdf"), text)

    assert len(result.transactions) == 2
    assert result.transactions[0].amount_native == Decimal("-4.90")
    assert result.transactions[1].amount_native == Decimal("-90.00")


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
