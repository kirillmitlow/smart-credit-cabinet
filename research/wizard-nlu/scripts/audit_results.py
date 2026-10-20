"""Check raw evidence, frozen thresholds, dataset separation, and protected scope."""
import csv
import hashlib
import json
from itertools import combinations

import numpy as np

from common import CANDIDATES, LABELS, ROOT, SLOTS, read_data, softmax, write_csv


def main():
    datasets = {s: read_data(s) for s in ["dev", "test", "examples"]}
    seal = json.loads((ROOT / "results/evaluation_seal.json").read_text())
    assert seal["dataset_manifest"] == json.loads((ROOT / "dataset/manifest.json").read_text())
    for a, b in combinations(datasets, 2):
        assert not {r["id"] for r in datasets[a]} & {r["id"] for r in datasets[b]}
        assert not {r["text"].lower().strip() for r in datasets[a]} & {r["text"].lower().strip() for r in datasets[b]}
    checks = []
    for c in CANDIDATES:
        path = ROOT / "results" / f"{c['id']}_test_predictions.csv"
        if not path.exists():
            checks.append(dict(candidate=c["id"], check="test_evidence", status="not_measured", n=0))
            continue
        settings_path = ROOT / "results" / f"{c['id']}_settings.json"
        assert hashlib.sha256(settings_path.read_bytes()).hexdigest() == seal["settings_sha256"][c["id"]]
        settings = json.loads(settings_path.read_text())
        assert settings["code_hashes"] == seal["code_hashes"]
        for name, digest in settings["code_hashes"].items():
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, (c["id"], name)
        with path.open() as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == len(datasets["test"]) * len(SLOTS)
        expected_ids = {(r["id"], s) for r in datasets["test"] for s in SLOTS}
        assert {(r["id"], r["slot"]) for r in rows} == expected_ids
        expected_text = {r["id"]: r["text"] for r in datasets["test"]}
        expected_gold = {r["id"]: r["labels"] for r in datasets["test"]}
        for r in rows:
            slot = r["slot"]
            assert r["text"] == expected_text[r["id"]]
            assert r["gold"] == expected_gold[r["id"]][slot]
            probabilities = json.loads(r["probabilities"])
            assert list(probabilities) == LABELS[slot]
            p = np.array(list(probabilities.values()))
            assert np.isfinite(p).all() and abs(p.sum() - 1) < 1e-9 and (p >= 0).all()
            raw = np.array(json.loads(r["raw_scores"]))
            assert np.allclose(p, softmax(raw, settings["slots"][slot]["temperature"]))
            pred = LABELS[slot][int(p.argmax())]
            assert pred == r["predicted"]
            assert (r["correct"] == "True") == (pred == r["gold"])
            accepted = pred != "UNKNOWN" and float(p.max()) >= settings["slots"][slot]["threshold"]
            assert accepted == (r["accepted"] == "True")
        with (ROOT / "results" / f"{c['id']}_test_latency.csv").open() as f:
            times = list(csv.DictReader(f))
        assert len(times) == len(datasets["test"])
        assert {t["id"] for t in times} == set(expected_text)
        elapsed = np.array([float(t["seconds"]) for t in times])
        assert np.isfinite(elapsed).all() and (elapsed > 0).all()
        with (ROOT / "results" / f"{c['id']}_test_runtime.csv").open() as f:
            runtime = next(csv.DictReader(f))
        assert np.isclose(np.percentile(elapsed, 50), float(runtime["latency_p50_s"]))
        assert np.isclose(np.percentile(elapsed, 95), float(runtime["latency_p95_s"]))
        checks.append(dict(candidate=c["id"], check="probabilities_thresholds_and_split", status="passed", n=len(rows)))
    write_csv(ROOT / "results/audit.csv", checks)
    print("Audit complete:", checks)


if __name__ == "__main__":
    main()
