import pytest

from finance_tooling import healthcheck  # type: ignore[deprecated]


def test_healthcheck() -> None:
    with pytest.warns(DeprecationWarning, match="deprecated"):
        assert healthcheck() == "ok"  # type: ignore[deprecated]
