"""Audit recorded decisions and check CPU cosine numerics using Python scalar sums."""
import csv
import json
import math

import followup_synthetic20 as study
from common import CANDIDATES, LABELS, SLOTS, read_data


def main():
    out = study.OUT
    seal = json.loads((out / "seal.json").read_text())
    assert study.fingerprint() == seal["hashes"]
    source = {r["id"]: r for r in study.read_input()}
    paths = [out / f"{name}_predictions.csv" for name in seal["variants"]]
    before = {p.name: study.digest(p) for p in paths}
    predictions = {}
    for name, cfg in seal["variants"].items():
        rs = study.read_csv(out / f"{name}_predictions.csv")
        assert len(rs) == 120
        assert {(r["id"], r["slot"]) for r in rs} == {(ident, slot) for ident in source for slot in SLOTS}
        for r in rs:
            slot = r["slot"]
            assert r["gold"] == source[r["id"]]["labels"][slot]
            assert (r["unambiguous"] == "True") == (slot not in source[r["id"]]["ambiguous_slots"])
            p = json.loads(r["probabilities"])
            assert set(p) == set(LABELS[slot]) and abs(math.fsum(p.values()) - 1) < 1e-9
            assert all(math.isfinite(v) and 0 <= v <= 1 for v in p.values())
            pred = max(p, key=p.get)
            assert pred == r["predicted"]
            accepted = pred != "UNKNOWN" and p[pred] >= cfg["slots"][slot]["threshold"]
            assert accepted == (r["accepted"] == "True")
            assert (pred == r["gold"]) == (r["correct"] == "True")
        predictions[name] = {(r["id"], r["slot"]): r for r in rs}
    for summary in study.read_csv(out / "summary.csv"):
        rs = list(predictions[summary["variant"]].values())
        if summary["subset"] == "unambiguous":
            rs = [r for r in rs if r["unambiguous"] == "True"]
        accepted = [r for r in rs if r["accepted"] == "True"]
        assert int(summary["n_slot_answers"]) == len(rs)
        assert int(summary["accepted"]) == len(accepted)
        assert int(summary["accepted_correct"]) == sum(r["correct"] == "True" for r in accepted)
    # The inference emitted NumPy matmul warnings on this Mac. Validate every stored
    # USER2 class score against an independent scalar cosine calculation. This
    # re-encodes texts solely for numeric auditing, never replaces the held-out scores.
    from models import Embedding
    candidate = next(c for c in CANDIDATES if c["id"] == "user2-base")
    support = read_data("examples")
    model = Embedding(candidate, support)
    rows = list(source.values())
    vectors = model.encode([r["text"] for r in rows]).tolist()
    references = model.reference.tolist()
    norm_error = max(abs(math.sqrt(math.fsum(x * x for x in v)) - 1) for v in vectors + references)
    assert norm_error < 1e-5
    assert all(math.isfinite(x) for v in vectors + references for x in v)
    k = seal["variants"]["user2_original"]["knn_k"]
    max_error, compared = 0.0, 0
    for row, vector in zip(rows, vectors):
        cosines = [math.fsum(x * y for x, y in zip(vector, reference)) for reference in references]
        for slot in SLOTS:
            saved = json.loads(predictions["user2_original"][(row["id"], slot)]["raw_scores"])
            for label, actual in zip(LABELS[slot], saved):
                nearest = sorted([v for v, ref in zip(cosines, support) if ref["labels"][slot] == label], reverse=True)[:k]
                expected = math.fsum(nearest) / len(nearest)
                max_error = max(max_error, abs(actual - expected))
                assert math.isclose(actual, expected, abs_tol=2e-6, rel_tol=2e-6)
                compared += 1
    assert before == {p.name: study.digest(p) for p in paths}
    result = dict(status="passed", prediction_rows=360, scalar_cosine_scores_compared=compared,
                  max_absolute_score_error=max_error, max_embedding_norm_error=norm_error,
                  original_predictions_unchanged=True,
                  note="Extra encoding was a numerical audit after matmul warnings, not a new quality run or tuning")
    (out / "audit.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
