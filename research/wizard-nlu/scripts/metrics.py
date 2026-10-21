import numpy as np
from sklearn.metrics import accuracy_score, f1_score

from common import LABELS, gold, softmax


def calibrate(scores, y):
    temperatures = np.geomspace(0.005, 20, 160)
    losses = [-np.log(np.clip(softmax(scores, t)[np.arange(len(y)), y], 1e-12, 1)).mean()
              for t in temperatures]
    return float(temperatures[np.argmin(losses)])


def choose_threshold(probabilities, y, slot, min_count=5):
    pred = probabilities.argmax(1)
    confidence = probabilities.max(1)
    known = np.array([LABELS[slot][p] != "UNKNOWN" for p in pred])
    best = dict(threshold=1.01, dev_accepted=0, dev_selective_accuracy=None)
    for threshold in np.unique(confidence[known]):
        accepted = known & (confidence >= threshold)
        n = int(accepted.sum())
        acc = float((pred[accepted] == y[accepted]).mean())
        if n >= min_count and acc >= 0.95 and n > best["dev_accepted"]:
            best = dict(threshold=float(threshold), dev_accepted=n, dev_selective_accuracy=acc)
    return best


def wilson(correct, n):
    if not n:
        return None, None
    z = 1.959963984540054
    p = correct / n
    center = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return float(center - half), float(center + half)


def reliability(probs, y):
    confidence, pred = probs.max(1), probs.argmax(1)
    out = []
    for b in range(10):
        lo, hi = b / 10, (b + 1) / 10
        mask = (confidence >= lo) & ((confidence < hi) if b < 9 else (confidence <= hi))
        n = int(mask.sum())
        out.append(dict(bin_lower=lo, bin_upper=hi, n=n,
                        mean_confidence=float(confidence[mask].mean()) if n else None,
                        accuracy=float((pred[mask] == y[mask]).mean()) if n else None))
    return out


def evaluate(scores, rows, slot, settings):
    y = gold(rows, slot)
    p = softmax(scores, settings["temperature"])
    pred, conf = p.argmax(1), p.max(1)
    known = np.array([LABELS[slot][i] != "UNKNOWN" for i in pred])
    accept = known & (conf >= settings["threshold"])
    correct = pred == y
    bins = reliability(p, y)
    n, ac = int(accept.sum()), int(correct[accept].sum())
    low, high = wilson(ac, n)
    true_known = np.array([LABELS[slot][i] != "UNKNOWN" for i in y])
    false_known = (~true_known) & known
    stats = dict(n=len(rows), accuracy=float(accuracy_score(y, pred)),
                 macro_f1=float(f1_score(y, pred, labels=list(range(len(LABELS[slot]))), average="macro", zero_division=0)),
                 ece=sum(b["n"] / len(rows) * abs(b["accuracy"] - b["mean_confidence"]) for b in bins if b["n"]),
                 accepted=n, accepted_correct=ac, selective_accuracy=ac / n if n else None,
                 coverage=n / len(rows), selective_wilson_low=low, selective_wilson_high=high,
                 meets_95_test=(ac / n >= .95) if n else False,
                 known_gold_n=int(true_known.sum()),
                 correctly_filled_known_recall=int((accept & correct & true_known).sum()) / max(1, int(true_known.sum())),
                 invented_known_n=int(false_known.sum()),
                 invented_and_accepted_n=int((false_known & accept).sum()),
                 threshold=settings["threshold"], temperature=settings["temperature"])
    return stats, bins, p, accept
