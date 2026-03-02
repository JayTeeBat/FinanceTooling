"""Run guardrail evaluation for quality safety checks."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GuardrailThresholds:
    """Thresholds for strict ingestion guardrails."""

    reconciliation_pass_ratio_min: float = 0.90
    uncategorized_ratio_max: float = 0.98
    row_delta_abs_max: int = 20000


@dataclass(frozen=True)
class GuardrailResult:
    """Guardrail evaluation result."""

    violations: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return len(self.violations) == 0


def evaluate_guardrails(
    *,
    reconciliation_pass_ratio: float | None,
    uncategorized_ratio: float,
    new_rows: int,
    replaced_rows: int,
    thresholds: GuardrailThresholds | None = None,
) -> GuardrailResult:
    """Evaluate quality and row-delta guardrails."""
    active_thresholds = thresholds or GuardrailThresholds()
    violations: list[str] = []
    if (
        reconciliation_pass_ratio is not None
        and reconciliation_pass_ratio < active_thresholds.reconciliation_pass_ratio_min
    ):
        violations.append(
            "reconciliation_pass_ratio below threshold "
            f"({reconciliation_pass_ratio:.4f} < "
            f"{active_thresholds.reconciliation_pass_ratio_min:.4f})"
        )
    if uncategorized_ratio > active_thresholds.uncategorized_ratio_max:
        violations.append(
            "uncategorized_ratio above threshold "
            f"({uncategorized_ratio:.4f} > {active_thresholds.uncategorized_ratio_max:.4f})"
        )
    row_delta = new_rows - replaced_rows
    if abs(row_delta) > active_thresholds.row_delta_abs_max:
        violations.append(
            "row_delta exceeds threshold "
            f"({row_delta} with |delta| > {active_thresholds.row_delta_abs_max})"
        )
    return GuardrailResult(violations=tuple(violations))
