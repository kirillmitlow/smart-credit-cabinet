"""Run dev, freeze settings, then perform a single held-out test pass."""
import argparse
import hashlib
import json
import os
import platform
import resource
import sys
import time

import numpy as np
import psutil
from sklearn.metrics import f1_score

from common import CANDIDATES, LABELS, ROOT, SLOTS, gold, model_path, read_data, softmax, write_csv
from metrics import calibrate, choose_threshold, evaluate


def code_hashes():
    files = [ROOT / "scripts" / p for p in ("common.py", "models.py", "benchmark.py", "metrics.py", "amount_parser.py")]
    files += [ROOT / p for p in ("schema.json", "candidates.json", "pyproject.toml", "uv.lock", "modern/pyproject.toml", "modern/uv.lock")]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def write_predictions(candidate, split, rows, scores, settings, latencies, folds=None):
    records, metrics, bins_out = [], [], []
    for slot in SLOTS:
        stats, bins, probs, accept = evaluate(scores[slot], rows, slot, settings[slot])
        stats.update(candidate=candidate["id"], split=split, slot=slot)
        metrics.append(stats)
        for b in bins:
            bins_out.append(dict(candidate=candidate["id"], split=split, slot=slot, **b))
        for i, row in enumerate(rows):
            pred = int(probs[i].argmax())
            records.append(dict(candidate=candidate["id"], split=split, id=row["id"], slot=slot,
                                text=row["text"], gold=row["labels"][slot], predicted=LABELS[slot][pred],
                                confidence=float(probs[i, pred]), accepted=bool(accept[i]),
                                correct=LABELS[slot][pred] == row["labels"][slot],
                                probabilities=json.dumps(dict(zip(LABELS[slot], probs[i].tolist()))),
                                raw_scores=json.dumps(scores[slot][i].tolist()),
                                fold=int(folds[i]) if folds is not None else ""))
    prefix = ROOT / "results" / f"{candidate['id']}_{split}"
    write_csv(str(prefix) + "_predictions.csv", records)
    write_csv(str(prefix) + "_metrics.csv", metrics)
    write_csv(str(prefix) + "_reliability.csv", bins_out)
    if latencies:
        write_csv(str(prefix) + "_latency.csv", [dict(candidate=candidate["id"], split=split,
                  id=r["id"], seconds=t) for r, t in zip(rows, latencies)])


def measure(model, rows):
    scores = {s: [] for s in SLOTS}
    latencies = []
    for i, row in enumerate(rows):
        start = time.perf_counter()
        output = model.score(row["text"])
        latencies.append(time.perf_counter() - start)
        for s in SLOTS:
            assert np.isfinite(output[s]).all(), f"Non-finite scores: {s}/{row['id']}"
            scores[s].append(np.asarray(output[s], dtype=float))
        if i % 10 == 0:
            print("PROGRESS", i + 1, "/", len(rows), "last_s", round(latencies[-1], 3), flush=True)
    return {s: np.stack(v) for s, v in scores.items()}, latencies


def main():
    p = argparse.ArgumentParser()
    p.add_argument("phase", choices=["dev", "test", "human"])
    p.add_argument("--id", required=True, choices=[c["id"] for c in CANDIDATES])
    p.add_argument("--allow-repeat", action="store_true", help="Explicit reproduction, never tuning")
    args = p.parse_args()
    c = next(c for c in CANDIDATES if c["id"] == args.id)
    frozen = ROOT / "results/frozen" / f"{args.id}.json"
    output = ROOT / "results" / f"{args.id}_{args.phase}_predictions.csv"
    if output.exists() and not args.allow_repeat:
        raise SystemExit("Already run. Use a clean copy for reproduction, or explicit --allow-repeat.")
    rows = read_data("dev" if args.phase == "dev" else args.phase)
    if not rows:
        print("No human rows yet. Add 15–20 annotated JSONL rows; no inference run performed.")
        return
    if args.phase != "dev":
        settings_file = json.loads(frozen.read_text())
        settings = settings_file["slots"]
        current = code_hashes()
        # Report/aggregation scripts may be added later; all existing prediction code must match.
        for name, digest in settings_file["code_hashes"].items():
            assert current.get(name) == digest, f"Changed after dev freeze: {name}"
    import models
    rss_before = psutil.Process().memory_info().rss
    folds, training_seconds = None, 0
    if args.phase == "dev" and c["kind"] == "finetuned":
        scores, folds, training_seconds = models.train_oof(c, rows)
    start = time.perf_counter()
    model = models.load(c, read_data("examples"))
    load_seconds = time.perf_counter() - start
    if load_seconds > 1200:
        raise TimeoutError("Model startup exceeded 20 minutes")
    rss_loaded = psutil.Process().memory_info().rss
    # Warm-up uses only dev, regardless of evaluated split.
    warmup = []
    for row in read_data("dev")[:3]:
        begin = time.perf_counter()
        model.score(row["text"])
        warmup.append(time.perf_counter() - begin)
    print("MODEL_READY", flush=True)
    if args.phase == "dev" and c["kind"] == "embedding":
        vectors = model.encode([r["text"] for r in rows])
        best = (-1, 1)
        for k in [1, 3]:
            trial = model.scores_from_vector(vectors, k=k)
            f1 = np.mean([f1_score(gold(rows, s), trial[s].argmax(1), labels=list(range(len(LABELS[s]))),
                                  average="macro", zero_division=0) for s in SLOTS])
            if f1 > best[0]:
                best = (f1, k)
        model.k = best[1]
    if args.phase != "dev" and c["kind"] == "embedding":
        model.k = settings_file["knn_k"]
    if not (args.phase == "dev" and c["kind"] == "finetuned"):
        scores, latencies = measure(model, rows)
    else:
        # These are OOF scores. Time the final trained model separately on dev, without using its answers.
        _, latencies = measure(model, rows)
    if args.phase == "dev":
        settings = {}
        for s in SLOTS:
            t = calibrate(scores[s], gold(rows, s))
            settings[s] = dict(temperature=t, **choose_threshold(softmax(scores[s], t), gold(rows, s), s))
        frozen.parent.mkdir(exist_ok=True)
        data = dict(candidate=c, slots=settings, knn_k=getattr(model, "k", None),
                    dataset_manifest=json.loads((ROOT / "dataset/manifest.json").read_text()),
                    code_hashes=code_hashes(), created_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        frozen.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        # Keep the concrete recommended settings tracked, independent of ignored local checkpoints.
        (ROOT / "results" / f"{args.id}_settings.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    write_predictions(c, args.phase, rows, scores, settings, latencies, folds)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_bytes = peak if sys.platform == "darwin" else peak * 1024
    disk = sum(p.stat().st_size for p in model_path(c).rglob("*") if p.is_file() and not p.name.endswith(".partial"))
    if c["kind"] == "finetuned":
        disk += (ROOT / "checkpoints/rubert-finetuned.pt").stat().st_size
    runtime = dict(candidate=args.id, split=args.phase, device="cpu", dtype="float32", threads=models.THREADS,
                   torch_version=models.torch.__version__, transformers_version=__import__("transformers").__version__,
                   python=platform.python_version(), platform=platform.platform(), arch=platform.machine(),
                   physical_ram_bytes=psutil.virtual_memory().total, logical_cpus=psutil.cpu_count(),
                   load_seconds=load_seconds, warmup_seconds=json.dumps(warmup), training_seconds=training_seconds,
                   rss_before_bytes=rss_before, rss_loaded_bytes=rss_loaded, peak_rss_bytes=peak_bytes,
                   disk_bytes=disk, latency_p50_s=float(np.percentile(latencies, 50)),
                   latency_p95_s=float(np.percentile(latencies, 95)),
                   model_revision=json.loads((ROOT / "model_manifest.json").read_text())[c["repo"]]["revision"])
    write_csv(ROOT / "results" / f"{args.id}_{args.phase}_runtime.csv", [runtime])
    print(json.dumps(runtime, indent=2), flush=True)


if __name__ == "__main__":
    main()
