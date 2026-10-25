"""Fail closed when an exact planning search exceeds its supported work budget."""

MAX_CHANGE_COMBINATIONS = 2_000
MAX_CANDIDATES = 5_000
MAX_PLANNING_SECONDS = 8.0


class PlanningBudgetExceeded(ValueError):
    """No recommendation is emitted from an incomplete search."""
