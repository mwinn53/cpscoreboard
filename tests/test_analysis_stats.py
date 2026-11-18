"""The Analysis tab's statistics (app/analysis_stats.py, on SciPy): exact p-values for small samples, BCa intervals."""

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


def test_wilcoxon_signed_rank_is_exact_for_small_samples():
    w = S.wilcoxon_signed_rank([74, 62, 88, 45, 91, 57, 50, 68, 33, 79, 66, 71], 50)
    assert w.p == approx(0.013671875) and (w.n, w.above, w.w) == (11, 9, 60.0)   # the normal approximation: 0.018


def test_rank_correlations_match_scipy():
    sp = S.spearman([1, 2, 2, 3, 5, 8, 12, 15, 20, 26, 40, 61], [64, 52, 70, 48, 55, 61, 50, 57, 49, 53, 51, 50])
    assert sp.r == approx(-0.45964912280701764) and sp.p == approx(0.13273946871827977, rel=1e-6)
    kt = S.kendall_tau(list(range(11)), [85, 87, 95, 87, 94, 80, 93, 75, 89, 91, 68])   # a tie: approximate
    assert kt.r == approx(-0.18349396085439343) and kt.p == approx(0.43487965849578336, rel=1e-9)
    exact = S.kendall_tau(list(range(8)), [55, 61, 49, 70, 66, 72, 80, 77])             # no ties: exact
    assert exact.r == approx(0.7142857142857142) and exact.p == approx(0.014136904761904762) and exact.significant
    assert S.kendall_tau([1, 2, 3, 4, 5], [7, 7, 7, 7, 7]) is None


def test_bca_intervals_are_stable_and_contain_the_estimate():
    lo, hi = S.bootstrap_median(A)
    assert lo <= 62.5 <= hi and S.bootstrap_median(A) == (lo, hi)    # seeded: same every time
    d, dlo, dhi = S.bootstrap_median_diff(A, B)
    assert d == 62.5 - 49 and dlo <= d <= dhi and dlo > 0
    assert S.bootstrap_median([5, 5, 5, 5]) == (5, 5)                  # no spread: no interval to compute
    assert S.bootstrap_median([1, 2]) is None


def test_p_text():
    assert (S.p_text(0.0004), S.p_text(0.0042), S.p_text(0.43)) == ("p < 0.001", "p = 0.004", "p = 0.43")
