from bisect import bisect_right
from collections import Counter
from math import exp, fsum, log


def _cutoff(values, parts):
    ordered = sorted(values)
    return tuple(
        sorted(
            {ordered[i * len(ordered) // parts] for i in range(1, parts)}
            - {ordered[0], ordered[-1]}
        )
    )


def train(rows):
    cuts = tuple(_cutoff(col, 5) for col in zip(*(row.raw for row in rows)))
    classes = Counter(int(row.y) for row in rows)
    bins = {index: [Counter() for _ in cuts] for index in classes}
    for record in rows:
        for i, (cuts_here, reading) in enumerate(zip(cuts, record.raw)):
            bins[int(record.y)][i][bisect_right(cuts_here, reading)] += 1
    densities = {}
    for cohort, acc in bins.items():
        densities[cohort] = [
            [
                log((counts[bin_id] + 0.7) / (classes[cohort] + 0.7 * (len(edges) + 1)))
                for bin_id in range(len(edges) + 1)
            ]
            for counts, edges in zip(acc, cuts)
        ]
    return {
        "histogram": densities,
        "bins": cuts,
        "prior_log_odds": log((classes[1] + 1) / (classes[0] + 1)),
        "completed": classes[0],
        "cancelled": classes[1],
    }


def infer(state, signal):
    keys = [
        bisect_right(edges, value) for edges, value in zip(state["bins"], signal.vector)
    ]
    scores = state["histogram"]
    ratio = state["prior_log_odds"] + fsum(
        scores[1][i][col] - scores[0][i][col] for i, col in enumerate(keys)
    )
    return 1 / (1 + exp(-max(-42.0, min(42.0, ratio))))


def explain(state):
    return {
        "bucket_bounds": state["bins"],
        "prior_log_odds": state["prior_log_odds"],
        "cancelled_holds": state["cancelled"],
        "honored_holds": state["completed"],
        "smoothing": 0.7,
    }
