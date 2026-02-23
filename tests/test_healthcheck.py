from finance_tooling import healthcheck


def test_healthcheck() -> None:
    assert healthcheck() == "ok"
