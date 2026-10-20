"""Check raw evidence, frozen thresholds, dataset separation, and protected scope."""
import csv
import hashlib
import json
from itertools import combinations

import numpy as np

from common import CANDIDATES, LABELS, ROOT, SLOTS, read_data, softmax, write_csv


def main():
    datasets = {s: read_data(s) for s in ["dev", "test", "examples"]}
    for a, b in combinations(datasets, 2):
        assert not {r["id"] for r in datasets[a]} & {r["id"] for r in datasets[b]}
        assert not {r["text"].lower().strip() for r in datasets[a]} & {r["text"].lower().strip() for r in datasets[b]}
    checks = []
    for c in CANDIDATES:
        path = ROOT / "results" / f"{c['id']}_test_predictions.csv"
        if not path.exists():
            checks.append(dict(candidate=c["id"], check="test_evidence", status="not_measured", n=0))
            continue
        settings = json.loads((ROOT / "results" / f"{c['id']}_settings.json").read_text())
        for name, digest in settings["code_hashes"].items():
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, (c["id"], name)
        with path.open() as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == len(datasets["test"]) * len(SLOTS)
        expected_ids = {(r["id"], s) for r in datasets["test"] for s in SLOTS}
        assert {(r["id"], r["slot"]) for r in rows} == expected_ids
        expected_text = {r["id"]: r["text"] for r in datasets["test"]}
        for r in rows:
            slot = r["slot"]
            assert r["text"] == expected_text[r["id"]]
            probabilities = json.loads(r["probabilities"])
            assert list(probabilities) == LABELS[slot]
            p = np.array(list(probabilities.values()))
            assert np.isfinite(p).all() and abs(p.sum() - 1) < 1e-9 and (p >= 0).all()
            raw = np.array(json.loads(r["raw_scores"]))
            assert np.allclose(p, softmax(raw, settings["slots"][slot]["temperature"]))
            pred = LABELS[slot][int(p.argmax())]
            assert pred == r["predicted"]
            accepted = pred != "UNKNOWN" and float(p.max()) >= settings["slots"][slot]["threshold"]
            assert accepted == (r["accepted"] == "True")
        checks.append(dict(candidate=c["id"], check="probabilities_thresholds_and_split", status="passed", n=len(rows)))
    write_csv(ROOT / "results/audit.csv", checks)
    print("Audit complete:", checks)


if __name__ == "__main__":
    main()
