"""Shared invariants for probabilistic model outputs."""

from collections.abc import Sequence
from math import isclose


def validate_result_probabilities(probabilities: Sequence[float]) -> None:
    """Validate a home/draw/away probability vector."""

    if len(probabilities) != 3:
        raise ValueError("result probabilities must contain home, draw, and away")
    if any(value < 0 or value > 1 for value in probabilities):
        raise ValueError("result probabilities must be between zero and one")
    if not isclose(sum(probabilities), 1.0, abs_tol=1e-9):
        raise ValueError("result probabilities must sum to one")
