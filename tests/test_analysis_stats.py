"""The Analysis tab's statistics (app/analysis_stats.py), checked against SciPy's results for the same data."""

from pytest import approx

from app import analysis_stats as S

A = [72, 55, 61, 48, 90, 55, 67, 81, 59, 64, 70, 52]
B = [40, 55, 38, 61, 47, 52, 33, 58, 45, 50, 49, 62, 41, 55, 36]


def test_ranks_share_ties():
    assert S.ranks([10, 20, 20, 5]) == [2.0, 3.5, 3.5, 1.0]


def test_mann_whitney_matches_scipy():
    mw = S.mann_whitney(A, B)
    assert mw.p == approx(0.0016156977637125413, rel=1e-9) and mw.significant
    assert mw.prob_sup == approx(mw.u / (len(A) * len(B)))
    lo, hi = mw.prob_sup_ci
    assert lo < mw.prob_sup < hi <= 1
    assert S.mann_whitney(A[:4], B) is None          # too few to test


def test_wilcoxon_signed_rank_matches_scipy():
    w = S.wilcoxon_signed_rank([74, 62, 88, 45, 91, 57, 50, 68, 33, 79, 66, 71], 50)
    assert w.p == approx(0.01846608649691215, rel=1e-9) and (w.n, w.above) == (11, 9)


def test_rank_correlations_match_scipy():
    sp = S.spearman([1, 2, 2, 3, 5, 8, 12, 15, 20, 26, 40, 61], [64, 52, 70, 48, 55, 61, 50, 57, 49, 53, 51, 50])
    assert sp.r == approx(-0.45964912280701764) and sp.p == approx(0.13273946871827977, rel=1e-6)
    kt = S.kendall_tau(list(range(11)), [85, 87, 95, 87, 94, 80, 93, 75, 89, 91, 68])
    assert kt.r == approx(-0.18349396085439343) and kt.p == approx(0.43487965849578336, rel=1e-9)


def test_bootstrap_intervals_are_stable_and_contain_the_estimate():
    lo, hi = S.bootstrap_median(A)
    assert lo <= 62.5 <= hi and S.bootstrap_median(A) == (lo, hi)    # seeded: same every time
    d, dlo, dhi = S.bootstrap_median_diff(A, B)
    assert d == 62.5 - 49 and dlo <= d <= dhi and dlo > 0


def test_p_text():
    assert (S.p_text(0.0004), S.p_text(0.0042), S.p_text(0.43)) == ("p < 0.001", "p = 0.004", "p = 0.43")
