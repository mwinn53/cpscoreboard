"""Statistical tests for the Analysis tab, on SciPy.

Scores are skewed, with outliers and ties, so the tests are rank-based and the
intervals come from the bootstrap. Effect sizes come first; p-values back them up.
SciPy picks **exact** p-values where they're feasible (small samples without ties)
and the normal approximation otherwise, which matters most for the season pages'
small samples.

* ``mann_whitney``: two groups (e.g. a state against the rest of the division):
  the U test, and the **probability of superiority** (the chance a random team from
  the first group outscores a random team from the second, ties half) with a
  Hanley–McNeil interval.
* ``bootstrap_median`` / ``bootstrap_median_diff``: **BCa** (bias-corrected and
  accelerated) intervals for a median and a difference in medians, seeded so a
  report doesn't change between page loads; plain percentile intervals when BCa
  can't be computed (e.g. a group with almost no spread).
* ``wilcoxon_signed_rank``: are values centred above a reference (e.g. our teams'
  percentiles against 50)?
* ``spearman`` and ``kendall_tau``: rank correlations with p-values.
* ``holm``: Holm's step-down correction when several tests are read together
  (e.g. one per image family).
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass

import numpy as np
from scipy import stats as st

Z95 = 1.959963984540054
REPS = 2000
SEED = 19


def ranks(values: list[float]) -> list[float]:
    """1-based ranks, ties sharing their average rank."""
    return [float(r) for r in st.rankdata(values, method="average")]


@dataclass(frozen=True)
class MannWhitney:
    n1: int
    n2: int
    u: float
    p: float
    prob_sup: float            # P(random a > random b), ties count half
    prob_sup_ci: tuple[float, float]

    @property
    def significant(self) -> bool:
        return self.p < 0.05


def mann_whitney(a: list[float], b: list[float]) -> MannWhitney | None:
    n1, n2 = len(a), len(b)
    if n1 < 5 or n2 < 5:
        return None
    res = st.mannwhitneyu(a, b, alternative="two-sided", method="auto")
    u = float(res.statistic)
    auc = u / (n1 * n2)
    q1, q2 = auc / (2 - auc), 2 * auc * auc / (1 + auc)
    se = math.sqrt(max(auc * (1 - auc) + (n1 - 1) * (q1 - auc * auc) + (n2 - 1) * (q2 - auc * auc), 0) / (n1 * n2))
    p = float(res.pvalue)
    return MannWhitney(n1, n2, u, 1.0 if math.isnan(p) else p, auc,
                       (max(0.0, auc - Z95 * se), min(1.0, auc + Z95 * se)))


def _interval(data: tuple, statistic) -> tuple[float, float] | None:
    """A 95% bootstrap interval: BCa, or the percentile method when BCa can't be computed."""
    for method in ("BCa", "percentile"):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # BCa warns (and returns NaN) on degenerate resamples
            res = st.bootstrap(data, statistic, n_resamples=REPS, confidence_level=0.95, method=method,
                               rng=np.random.default_rng(SEED), vectorized=True)
        lo, hi = float(res.confidence_interval.low), float(res.confidence_interval.high)
        if not (math.isnan(lo) or math.isnan(hi)):
            return lo, hi
    return None


def bootstrap_median(a: list[float]) -> tuple[float, float] | None:
    if len(a) < 3:
        return None
    if len(set(a)) == 1:
        return a[0], a[0]
    return _interval((np.asarray(a, dtype=float),), lambda x, axis: np.median(x, axis=axis))


def bootstrap_median_diff(a: list[float], b: list[float]) -> tuple[float, float, float] | None:
    """median(a) - median(b), with a 95% interval."""
    if len(a) < 3 or len(b) < 3:
        return None
    d = float(np.median(a) - np.median(b))
    ci = _interval((np.asarray(a, dtype=float), np.asarray(b, dtype=float)),
                   lambda x, y, axis: np.median(x, axis=axis) - np.median(y, axis=axis))
    return (d, *ci) if ci else None


@dataclass(frozen=True)
class SignedRank:
    n: int            # non-zero differences
    above: int        # how many were above the reference
    w: float          # sum of positive ranks
    p: float

    @property
    def significant(self) -> bool:
        return self.p < 0.05


def wilcoxon_signed_rank(values: list[float], reference: float = 0.0) -> SignedRank | None:
    d = [v - reference for v in values if v != reference]
    n = len(d)
    if n < 6:
        return None
    res = st.wilcoxon(d, alternative="two-sided", method="auto")
    r = ranks([abs(x) for x in d])
    w = sum(rk for rk, x in zip(r, d) if x > 0)
    return SignedRank(n, sum(1 for x in d if x > 0), w, float(res.pvalue))


@dataclass(frozen=True)
class Correlation:
    n: int
    r: float
    p: float

    @property
    def significant(self) -> bool:
        return self.p < 0.05


def spearman(x: list[float], y: list[float]) -> Correlation | None:
    n = len(x)
    if n < 5 or len(set(x)) < 2 or len(set(y)) < 2:
        return None
    res = st.spearmanr(x, y)
    return Correlation(n, float(res.statistic), float(res.pvalue))


def kendall_tau(x: list[float], y: list[float]) -> Correlation | None:
    """Kendall's tau-b (a trend over rounds: x = order); exact p-values for small samples without ties."""
    n = len(x)
    if n < 5 or len(set(x)) < 2 or len(set(y)) < 2:
        return None
    res = st.kendalltau(x, y, method="auto")
    return Correlation(n, float(res.statistic), float(res.pvalue))


def holm(ps: list[float]) -> list[float]:
    """Holm-adjusted p-values, in the order given: controls the chance of any false positive across the tests."""
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    out, running = [0.0] * m, 0.0
    for k, i in enumerate(order):
        running = max(running, min(1.0, (m - k) * ps[i]))
        out[i] = running
    return out


def p_text(p: float) -> str:
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}" if p < 0.01 else f"p = {p:.2f}"
