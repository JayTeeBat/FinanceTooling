import pytest

from finance_tooling import healthcheck


def test_healthcheck() -> None:
    with pytest.warns(DeprecationWarning, match="deprecated"):
        assert healthcheck() == "ok"
