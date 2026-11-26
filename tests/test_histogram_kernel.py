from lightbooking.rental_hist_bayes.estimator import _cutoff


def test_duplicate_quantile_edges_keep_only_nontrivial_bins():
    assert _cutoff([10] * 90, 5) == ()
    assert _cutoff([1] * 12 + [2] * 15 + [3] * 12 + [4] * 11, 5) == (2, 3)
