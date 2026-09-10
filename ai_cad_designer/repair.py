"""Bounded, traceable parameter-repair loop for design validations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Callable, Mapping


@dataclass(frozen=True)
class RepairIssue:
    code: str
    summary: str
    reparable_parameters: tuple[str, ...] = ()
    evidence: dict[str, object] | None = None


@dataclass(frozen=True)
class RepairIteration:
    number: int
    parameters: dict[str, float]
    issues: tuple[RepairIssue, ...]
    change: dict[str, float]

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["issues"] = [asdict(issue) for issue in self.issues]
        return value


@dataclass(frozen=True)
class RepairResult:
    iterations: tuple[RepairIteration, ...]
    best_parameters: dict[str, float]
    status: str
    stop_reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "iterations": [item.to_dict() for item in self.iterations],
            "best_parameters": self.best_parameters,
            "status": self.status,
            "stop_reason": self.stop_reason,
        }


Suggestion = Callable[[tuple[RepairIssue, ...], Mapping[str, float]], Mapping[str, float]]
Evaluator = Callable[[Mapping[str, float]], tuple[RepairIssue, ...]]


def run_bounded_repair(
    initial_parameters: Mapping[str, float],
    initial_issues: tuple[RepairIssue, ...],
    *,
    allowed_ranges: Mapping[str, tuple[float, float]],
    suggest: Suggestion,
    evaluate: Evaluator,
    max_iterations: int = 3,
) -> RepairResult:
    """Try only whitelisted numeric changes and retain every attempted state."""
    if not 1 <= max_iterations <= 10:
        raise ValueError("max_iterations must be between 1 and 10")
    current = {name: float(value) for name, value in initial_parameters.items()}
    if set(current) - set(allowed_ranges):
        raise ValueError("initial parameters must be in allowed_ranges")
    for name, value in current.items():
        lower, upper = allowed_ranges[name]
        if not isfinite(value) or not lower <= value <= upper:
            raise ValueError(f"initial parameter {name} is outside its allowed range")

    issues = tuple(initial_issues)
    history = [RepairIteration(0, dict(current), issues, {})]
    best = dict(current)
    best_score = len(issues)
    seen = {tuple(sorted(current.items()))}
    for number in range(1, max_iterations + 1):
        if not issues:
            return RepairResult(tuple(history), dict(current), "resolved", "all_constraints_passed")
        permitted = set().union(*(issue.reparable_parameters for issue in issues))
        if not permitted:
            return RepairResult(tuple(history), best, "stopped", "manual_measurement_or_hard_constraint")
        try:
            change = {name: float(value) for name, value in suggest(issues, current).items()}
        except Exception:
            return RepairResult(tuple(history), best, "stopped", "planner_error")
        if not change or set(change) - permitted or set(change) - set(allowed_ranges):
            return RepairResult(tuple(history), best, "stopped", "invalid_suggestion")
        candidate = {**current, **change}
        if any(
            not isfinite(value) or not allowed_ranges[name][0] <= value <= allowed_ranges[name][1]
            for name, value in change.items()
        ):
            return RepairResult(tuple(history), best, "stopped", "invalid_suggestion")
        key = tuple(sorted(candidate.items()))
        if key in seen:
            return RepairResult(tuple(history), best, "stopped", "duplicate_suggestion")
        seen.add(key)
        try:
            issues = tuple(evaluate(candidate))
        except Exception:
            return RepairResult(tuple(history), best, "stopped", "validation_error")
        history.append(RepairIteration(number, dict(candidate), issues, change))
        current = candidate
        if len(issues) < best_score:
            best, best_score = dict(candidate), len(issues)
    return RepairResult(tuple(history), best, "stopped", "iteration_limit")
