"""Statistical tests for the Analysis tab, in plain Python (no SciPy in the image).

Scores are skewed, with outliers and ties, so the tests are rank-based and the
intervals come from the bootstrap. Effect sizes come first; p-values back them up.

* ``mann_whitney``: two groups (e.g. a state against the rest of the division):
  the U test (normal approximation with tie and continuity corrections; fine for
  the group sizes we test, at least 5 a side), and the **probability of
  superiority** (the chance a random team from the first group outscores a random
  team from the second, ties half) with a Hanley–McNeil interval.
* ``bootstrap_median`` / ``bootstrap_median_diff``: percentile intervals for a
  median and a difference in medians (seeded, so a report doesn't change between
  page loads).
* ``wilcoxon_signed_rank``: are paired values centred above a reference (e.g. our
  teams' percentiles against 50)?
* ``spearman`` and ``kendall_tau``: rank correlations with approximate p-values.

Checked against SciPy in tests/test_analysis_stats.py.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass

Z95 = 1.959963984540054
REPS = 1000
SEED = 19


def norm_sf(z: float) -> float:
    """P(Z > z) for a standard normal."""
    return 0.5 * math.erfc(z / math.sqrt(2))


def two_sided(z: float) -> float:
    return min(1.0, 2 * norm_sf(abs(z)))


def ranks(values: list[float]) -> list[float]:
    """1-based ranks, ties sharing their average rank."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def _tie_term(values: list[float]) -> float:
    counts: dict[float, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return sum(t ** 3 - t for t in counts.values())


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
    r = ranks(list(a) + list(b))
    u = sum(r[:n1]) - n1 * (n1 + 1) / 2
    n = n1 + n2
    mu = n1 * n2 / 2
    var = n1 * n2 / 12 * ((n + 1) - _tie_term(list(a) + list(b)) / (n * (n - 1)))
    if var <= 0:
        p = 1.0
    else:
        z = (abs(u - mu) - 0.5) / math.sqrt(var)
        p = two_sided(max(z, 0.0))
    auc = u / (n1 * n2)
    q1, q2 = auc / (2 - auc), 2 * auc * auc / (1 + auc)
    se = math.sqrt(max(auc * (1 - auc) + (n1 - 1) * (q1 - auc * auc) + (n2 - 1) * (q2 - auc * auc), 0) / (n1 * n2))
    return MannWhitney(n1, n2, u, p, auc, (max(0.0, auc - Z95 * se), min(1.0, auc + Z95 * se)))


def _percentiles(values: list[float], lo: float = 0.025, hi: float = 0.975) -> tuple[float, float]:
    v = sorted(values)
    return v[int(lo * (len(v) - 1))], v[int(math.ceil(hi * (len(v) - 1)))]


def bootstrap_median(a: list[float], reps: int = REPS, seed: int = SEED) -> tuple[float, float] | None:
    if len(a) < 3:
        return None
    rng = random.Random(seed)
    n = len(a)
    meds = [statistics.median(rng.choices(a, k=n)) for _ in range(reps)]
    return _percentiles(meds)


def bootstrap_median_diff(a: list[float], b: list[float], reps: int = REPS,
                          seed: int = SEED) -> tuple[float, float, float] | None:
    """median(a) - median(b), with a 95% percentile interval."""
    if len(a) < 3 or len(b) < 3:
        return None
    rng = random.Random(seed)
    diffs = [statistics.median(rng.choices(a, k=len(a))) - statistics.median(rng.choices(b, k=len(b)))
             for _ in range(reps)]
    lo, hi = _percentiles(diffs)
    return statistics.median(a) - statistics.median(b), lo, hi


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
    r = ranks([abs(x) for x in d])
    w = sum(rk for rk, x in zip(r, d) if x > 0)
    mu = n * (n + 1) / 4
    var = n * (n + 1) * (2 * n + 1) / 24 - _tie_term([abs(x) for x in d]) / 48
    z = (abs(w - mu) - 0.5) / math.sqrt(var) if var > 0 else 0.0
    return SignedRank(n, sum(1 for x in d if x > 0), w, two_sided(max(z, 0.0)))


@dataclass(frozen=True)
class Correlation:
    n: int
    r: float
    p: float

    @property
    def significant(self) -> bool:
        return self.p < 0.05


def spearman(x: list[float], y: list[float]) -> Correlation | None:
    """Rank correlation; p from the t approximation's normal limit (fine for n >= 10)."""
    n = len(x)
    if n < 5:
        return None
    rx, ry = ranks(list(x)), ranks(list(y))
    try:
        rho = statistics.correlation(rx, ry)
    except statistics.StatisticsError:
        return None
    if abs(rho) >= 1:
        return Correlation(n, rho, 0.0)
    t = rho * math.sqrt((n - 2) / (1 - rho * rho))
    return Correlation(n, rho, _t_two_sided(t, n - 2))


def kendall_tau(x: list[float], y: list[float]) -> Correlation | None:
    """Kendall's tau-b with the normal approximation (a trend over rounds: x = order)."""
    n = len(x)
    if n < 5:
        return None
    s = 0
    for i in range(n):
        for j in range(i + 1, n):
            a = (x[i] > x[j]) - (x[i] < x[j])
            b = (y[i] > y[j]) - (y[i] < y[j])
            s += a * b
    n0 = n * (n - 1) / 2
    tx, ty = _pairs_tied(x), _pairs_tied(y)
    denom = math.sqrt((n0 - tx) * (n0 - ty))
    if denom == 0:
        return None
    tau = s / denom
    vx, vy = _tie_var(x), _tie_var(y)
    v0 = n * (n - 1) * (2 * n + 5)
    var = (v0 - vx - vy) / 18
    var += (_tie_sum(x, 1) * _tie_sum(y, 1)) / (2 * n * (n - 1))
    var += (_tie_sum(x, 2) * _tie_sum(y, 2)) / (9 * n * (n - 1) * (n - 2))
    z = s / math.sqrt(var) if var > 0 else 0.0
    return Correlation(n, tau, two_sided(z))


def _counts(v: list[float]) -> list[int]:
    c: dict[float, int] = {}
    for x in v:
        c[x] = c.get(x, 0) + 1
    return [t for t in c.values() if t > 1]


def _pairs_tied(v: list[float]) -> float:
    return sum(t * (t - 1) / 2 for t in _counts(v))


def _tie_var(v: list[float]) -> float:
    return sum(t * (t - 1) * (2 * t + 5) for t in _counts(v))


def _tie_sum(v: list[float], kind: int) -> float:
    if kind == 1:
        return sum(t * (t - 1) for t in _counts(v))
    return sum(t * (t - 1) * (t - 2) for t in _counts(v))


def _t_two_sided(t: float, df: int) -> float:
    """Two-sided p for Student's t, via the regularized incomplete beta function."""
    x = df / (df + t * t)
    return min(1.0, _betainc(df / 2, 0.5, x))


def _betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b) (continued fraction, Numerical Recipes)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    if x < (a + 1) / (a + b + 2):
        return math.exp(lbeta) * _betacf(a, b, x) / a
    return 1 - math.exp(lbeta) * _betacf(b, a, 1 - x) / b


def _betacf(a: float, b: float, x: float) -> float:
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > tiny else tiny)
        c = 1 + aa / c if abs(1 + aa / c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > tiny else tiny)
        c = 1 + aa / c if abs(1 + aa / c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-12:
            break
    return h


def p_text(p: float) -> str:
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}" if p < 0.01 else f"p = {p:.2f}"
