"""Small, dependency-free interval estimates.

Survival and success rates are reported with the *task* as the unit: a task contributes its
own mean over seeds, and the interval is a percentile bootstrap over tasks. Seeds of one task
are not independent draws (the same page template, the same failure mode), so pooling them as
if they were would overstate precision.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (0, 0 for n == 0)."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("mean of nothing")
    return sum(values) / len(values)


def bootstrap_mean_ci(
    values: Sequence[float], reps: int = 2000, seed: int = 0, level: float = 0.95
) -> tuple[float, float]:
    """Percentile bootstrap interval for the mean of ``values`` (one value per task)."""
    if not values:
        raise ValueError("bootstrap of nothing")
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(reps))
    lo = means[int((1 - level) / 2 * reps)]
    hi = means[min(reps - 1, int((1 + level) / 2 * reps))]
    return (lo, hi)


def quantile(values: Sequence[float], q: float) -> float:
    """Linear-interpolated quantile, ``q`` in [0, 1]."""
    if not values:
        raise ValueError("quantile of nothing")
    ordered = sorted(values)
    pos = q * (len(ordered) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)
