"""Core package primitives for finance_tooling."""

from __future__ import annotations

import warnings

from typing_extensions import deprecated


@deprecated("finance_tooling.healthcheck() is deprecated and will be removed in a future cleanup.")
def healthcheck() -> str:
    """Deprecated smoke-check sentinel retained for compatibility only."""
    warnings.warn(
        "finance_tooling.healthcheck() is deprecated and will be removed in a future cleanup.",
        DeprecationWarning,
        stacklevel=2,
    )
    return "ok"
