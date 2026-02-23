"""Shared core primitives for the tooling package."""


def healthcheck() -> str:
    """Return a stable sentinel value for smoke checks."""
    return "ok"
