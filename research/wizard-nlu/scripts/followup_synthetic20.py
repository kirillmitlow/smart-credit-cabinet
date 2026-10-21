"""A sealed follow-up: old-dev-only threshold selection, then 20 new synthetic texts."""
import argparse
import copy
import csv
import gc
import hashlib
import json
import platform
import time
from pathlib import Path

import numpy as np

from amount_parser import parse_amount
from benchmark import code_hashes
from common import CANDIDATES, LABELS, ROOT, SLOTS, read_data, write_csv
from metrics import evaluate, wilson

DATA = ROOT / "dataset/followup_synthetic20.jsonl"
OUT = ROOT / "results/followup_synthetic20"
BASE = ROOT / "results/user2-base_settings.json"
LAYA = ROOT / "results/laya_settings.json"
DEV = ROOT / "results/user2-base_dev_predictions.csv"
POLICY = {"empirical_dev_accuracy": 1.0, "min_dev_accepted": 10,
          "temperature": "unchanged from original dev", "knn_k": 3,
          "population_accuracy_guarantee": False}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_csv(path):
    with Path(path).open() as f:
        return list(csv.DictReader(f))


def fingerprint():
    original = json.loads((ROOT / "results/evaluation_seal.json").read_text())
    hashes = code_hashes()
    assert hashes == original["code_hashes"], "Original prediction code changed"
    for ident, path in [("user2-base", BASE), ("laya", LAYA)]:
        assert digest(path) == original["settings_sha256"][ident], "Original settings changed"
    for path in [Path(__file__).resolve(), DATA, BASE, LAYA, DEV, ROOT / "model_manifest.json"]:
        hashes[str(path.relative_to(ROOT))] = digest(path)
    return hashes


def read_input():
    rows = [json.loads(line) for line in DATA.read_text().splitlines() if line.strip()]
    assert len(rows) == 20 and len({r["id"] for r in rows}) == 20
    old = [r for split in ["dev", "test", "examples"] for r in read_data(split)]
    old_ids = {r["id"] for r in old}
    old_texts = {" ".join(r["text"].casefold().split()) for r in old}
    new_texts = set()
    for r in rows:
        normalized = " ".join(r["text"].casefold().split())
        assert r["id"] not in old_ids and normalized not in old_texts | new_texts
        new_texts.add(normalized)
        assert r["provenance"]["kind"] == "user_supplied_synthetic"
        assert all(r["labels"][s] in LABELS[s] for s in SLOTS)
        amount = r["labels"]["amount_rub"]
        assert amount is None or (type(amount) is int and amount > 0)
        assert set(r["ambiguous_slots"]) <= set(SLOTS + ["amount_rub"])
    return rows


def strict_slot(records, temperature):
    """Maximize dev acceptance at 100% empirical accuracy and >=10 known answers."""
    known = [r for r in records if r["predicted"] != "UNKNOWN"]
    best = dict(temperature=temperature, threshold=1.01, dev_accepted=0,
                dev_selective_accuracy=None)
    for cutoff in sorted({float(r["confidence"]) for r in known}):
        selected = [r for r in known if float(r["confidence"]) >= cutoff]
        if len(selected) >= POLICY["min_dev_accepted"] and all(r["predicted"] == r["gold"] for r in selected):
            if len(selected) > best["dev_accepted"]:
                best.update(threshold=cutoff, dev_accepted=len(selected), dev_selective_accuracy=1.0)
    return best


def prepare(out):
    read_input()  # Freeze annotations and the ambiguity mask before any inference.
    hashes = fingerprint()
    baseline = json.loads(BASE.read_text())
    strict = copy.deepcopy(baseline)
    dev = read_csv(DEV)
    for slot in SLOTS:
        records = [r for r in dev if r["slot"] == slot]
        assert len(records) == 60 and all(r["split"] == "dev" for r in records)
        strict["slots"][slot] = strict_slot(records, baseline["slots"][slot]["temperature"])
        assert strict["slots"][slot]["threshold"] >= baseline["slots"][slot]["threshold"]
    variants = {"user2_original": baseline, "user2_strict": strict,
                "laya_original": json.loads(LAYA.read_text())}
    out.mkdir(parents=True, exist_ok=False)
    seal = dict(created_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                dataset_kind="user_supplied_synthetic", annotations="agent; provisional",
                policy=POLICY, hashes=hashes, variants=variants)
    (out / "seal.json").write_text(json.dumps(seal, ensure_ascii=False, indent=2) + "\n")
    thresholds = [dict(variant=name, slot=slot, **cfg["slots"][slot])
                  for name, cfg in variants.items() for slot in SLOTS]
    write_csv(out / "thresholds.csv", thresholds)
    print("SEALED: thresholds selected only from the original 60 dev phrases; no new inference")


def save_variant(out, name, cfg, rows, scores):
    predictions, metrics, bins = [], [], []
    for slot in SLOTS:
        for subset in ["all_provisional", "unambiguous"]:
            indices = [i for i, r in enumerate(rows) if subset == "all_provisional" or slot not in r["ambiguous_slots"]]
            stats, rbins, probs, accept = evaluate(scores[slot][indices], [rows[i] for i in indices], slot, cfg["slots"][slot])
            metrics.append(dict(variant=name, subset=subset, slot=slot, **stats))
            bins.extend(dict(variant=name, subset=subset, slot=slot, **b) for b in rbins)
            if subset != "all_provisional":
                continue
            for i, r in enumerate(rows):
                pred = LABELS[slot][int(probs[i].argmax())]
                predictions.append(dict(variant=name, id=r["id"], text=r["text"], slot=slot,
                    gold=r["labels"][slot], predicted=pred, confidence=float(probs[i].max()),
                    threshold=cfg["slots"][slot]["threshold"], accepted=bool(accept[i]),
                    correct=pred == r["labels"][slot], unambiguous=slot not in r["ambiguous_slots"],
                    probabilities=json.dumps(dict(zip(LABELS[slot], probs[i].tolist()))),
                    raw_scores=json.dumps(scores[slot][i].tolist())))
    write_csv(out / f"{name}_predictions.csv", predictions)
    write_csv(out / f"{name}_metrics.csv", metrics)
    write_csv(out / f"{name}_reliability.csv", bins)
    summary = []
    for subset in ["all_provisional", "unambiguous"]:
        rs = [r for r in predictions if subset == "all_provisional" or r["unambiguous"]]
        selected = [r for r in rs if r["accepted"]]
        correct = sum(r["correct"] for r in selected)
        lo, hi = wilson(correct, len(selected))
        summary.append(dict(variant=name, subset=subset, n_slot_answers=len(rs), accepted=len(selected),
            accepted_correct=correct, selective_accuracy=correct / len(selected) if selected else None,
            coverage=len(selected) / len(rs), accuracy_micro=sum(r["correct"] for r in rs) / len(rs),
            selective_wilson_low=lo, selective_wilson_high=hi))
    return summary, predictions


def run(out):
    seal = json.loads((out / "seal.json").read_text())
    assert seal["hashes"] == fingerprint(), "Changed after follow-up seal"
    rows = read_input()
    # Exclusive marker prevents silently re-running the same test after inspecting it.
    with (out / "inference_started.json").open("x") as f:
        json.dump({"started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f)
    import models
    summaries, runtime, variants_predictions = [], [], {}
    for ident, names in [("user2-base", ["user2_original", "user2_strict"]), ("laya", ["laya_original"])]:
        candidate = next(c for c in CANDIDATES if c["id"] == ident)
        model = models.load(candidate, read_data("examples"))
        if ident == "user2-base":
            model.k = seal["variants"]["user2_original"]["knn_k"]
        for r in read_data("dev")[:3]:
            model.score(r["text"])
        scores, times = {slot: [] for slot in SLOTS}, []
        for r in rows:
            start = time.perf_counter()
            output = model.score(r["text"])
            times.append(time.perf_counter() - start)
            for slot in SLOTS:
                assert np.isfinite(output[slot]).all()
                scores[slot].append(output[slot])
        scores = {slot: np.stack(values) for slot, values in scores.items()}
        for name in names:
            summary, predictions = save_variant(out, name, seal["variants"][name], rows, scores)
            summaries.extend(summary)
            variants_predictions[name] = predictions
        write_csv(out / f"{ident}_latency.csv", [dict(id=r["id"], seconds=t) for r, t in zip(rows, times)])
        runtime.append(dict(model=ident, device="cpu", dtype="float32", threads=models.THREADS,
            python=platform.python_version(), torch=models.torch.__version__,
            transformers=__import__("transformers").__version__,
            p50_s=float(np.percentile(times, 50)), p95_s=float(np.percentile(times, 95))))
        del model
        gc.collect()
    for original, strict in zip(variants_predictions["user2_original"], variants_predictions["user2_strict"]):
        assert original["id"] == strict["id"] and original["slot"] == strict["slot"]
        assert original["probabilities"] == strict["probabilities"]
        assert not strict["accepted"] or original["accepted"]
    write_csv(out / "summary.csv", summaries)
    write_csv(out / "runtime.csv", runtime)
    parser_rows = [dict(id=r["id"], text=r["text"], gold=r["labels"]["amount_rub"],
        predicted=parse_amount(r["text"]), unambiguous="amount_rub" not in r["ambiguous_slots"]) for r in rows]
    for r in parser_rows:
        r["correct"] = r["predicted"] == r["gold"]
    write_csv(out / "amount.csv", parser_rows)
    assert fingerprint() == seal["hashes"]
    (out / "completed.json").write_text(json.dumps(dict(
        completed_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        input_sha256=digest(DATA), checks="hashes, disjoint texts/ids, shared USER2 scores, strict acceptance subset",
        human_validation=False), indent=2) + "\n")
    for r in summaries:
        print(r["variant"], r["subset"], f"{r['accepted_correct']}/{r['accepted']}", "coverage", r["coverage"])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("phase", choices=["prepare", "run"])
    p.add_argument("--out", type=Path, default=OUT)
    args = p.parse_args()
    (prepare if args.phase == "prepare" else run)(args.out.resolve())


if __name__ == "__main__":
    main()
