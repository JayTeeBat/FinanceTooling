from pathlib import Path

from finance_tooling.parsers.labanquepostale import LaBanquePostaleParser
from finance_tooling.parsers.registry import select_parser


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
