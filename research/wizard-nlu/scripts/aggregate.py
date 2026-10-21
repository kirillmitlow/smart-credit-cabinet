"""Rebuild tables from saved predictions. Does not load models or fit thresholds."""
import csv
import json
from collections import Counter

import numpy as np

from common import CANDIDATES, LABELS, ROOT, SLOTS, read_data, write_csv
from metrics import wilson


def read_csv(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def main():
    all_metrics, all_bins, all_runtime, summary, confusions, errors, thresholds = [], [], [], [], [], [], []
    artifacts = []
    curves, pair_stats, baselines, parser_summaries = [], [], [], []
    manifest = json.loads((ROOT / "model_manifest.json").read_text())
    for c in CANDIDATES:
        ident = c["id"]
        local = ROOT / "models" / c["repo"].replace("/", "--")
        hashes_file = local / "download-sha256.json"
        if hashes_file.exists():
            for file, digest in json.loads(hashes_file.read_text()).items():
                if file.endswith(".safetensors"):
                    artifacts.append(dict(candidate=ident, repo=c["repo"],
                                          revision=manifest[c["repo"]]["revision"], file=file,
                                          bytes=(local / file).stat().st_size, sha256=digest))
        for split in ["dev", "test", "human"]:
            path = ROOT / "results" / f"{ident}_{split}_metrics.csv"
            if path.exists():
                all_metrics.extend(read_csv(path))
                all_bins.extend(read_csv(ROOT / "results" / f"{ident}_{split}_reliability.csv"))
                all_runtime.extend(read_csv(ROOT / "results" / f"{ident}_{split}_runtime.csv"))
        path = ROOT / "results" / f"{ident}_settings.json"
        if path.exists():
            settings = json.loads(path.read_text())
            for s in SLOTS:
                thresholds.append(dict(candidate=ident, slot=s, knn_k=settings["knn_k"], **settings["slots"][s]))
        path = ROOT / "results" / f"{ident}_test_predictions.csv"
        if not path.exists():
            summary.append(dict(candidate=ident, status="not_measured", repo=c["repo"],
                                license=manifest.get(c["repo"], {}).get("license", "UNSPECIFIED")))
            continue
        predictions = read_csv(path)
        slots = [m for m in all_metrics if m["candidate"] == ident and m["split"] == "test"]
        rt = next(r for r in all_runtime if r["candidate"] == ident and r["split"] == "test")
        accepted = [r for r in predictions if r["accepted"] == "True"]
        ncorrect = sum(r["correct"] == "True" for r in accepted)
        low, high = wilson(ncorrect, len(accepted))
        row = dict(candidate=ident, status="ok", repo=c["repo"], license=manifest[c["repo"]]["license"],
                   accuracy_mean=float(np.mean([float(m["accuracy"]) for m in slots])),
                   macro_f1_mean=float(np.mean([float(m["macro_f1"]) for m in slots])),
                   selective_accuracy_micro=ncorrect / len(accepted) if accepted else None,
                   selective_accuracy_macro=float(np.mean([float(m["selective_accuracy"]) for m in slots
                                                          if m["selective_accuracy"]])) if accepted else None,
                   coverage=len(accepted) / len(predictions), accepted=len(accepted), accepted_correct=ncorrect,
                   n_slot_answers=len(predictions), selective_wilson_low=low, selective_wilson_high=high,
                   slots_meeting_95=sum(m["meets_95_test"] == "True" for m in slots),
                   ece_mean=float(np.mean([float(m["ece"]) for m in slots])),
                   purpose_accuracy=float(next(m["accuracy"] for m in slots if m["slot"] == "purpose")),
                   latency_p50_s=rt["latency_p50_s"], latency_p95_s=rt["latency_p95_s"],
                   load_seconds=rt["load_seconds"], peak_ram_mib=int(rt["peak_rss_bytes"]) / 2**20,
                   disk_mib=int(rt["disk_bytes"]) / 2**20,
                   invented_and_accepted_n=sum(int(m["invented_and_accepted_n"]) for m in slots))
        summary.append(row)
        for slot in SLOTS:
            selected = [r for r in predictions if r["slot"] == slot]
            for true in LABELS[slot]:
                cells = Counter(r["predicted"] for r in selected if r["gold"] == true)
                for pred in LABELS[slot]:
                    confusions.append(dict(candidate=ident, slot=slot, gold=true, predicted=pred, n=cells[pred]))
            # Test-only diagnostic curve. Never reused to choose deployable thresholds.
            known = [r for r in selected if r["predicted"] != "UNKNOWN"]
            for cutoff in sorted({float(r["confidence"]) for r in known}, reverse=True):
                chosen = [r for r in known if float(r["confidence"]) >= cutoff]
                correct = sum(r["correct"] == "True" for r in chosen)
                curves.append(dict(candidate=ident, slot=slot, diagnostic_only=True, threshold=cutoff,
                                   accepted=len(chosen), coverage=len(chosen) / len(selected),
                                   selective_accuracy=correct / len(chosen)))
        for r in predictions:
            if r["correct"] == "False":
                errors.append({k: r[k] for k in ["candidate", "id", "slot", "text", "gold", "predicted", "confidence", "accepted"]})
        critical = [r for r in predictions if r["slot"] == "purpose" and
                    r["gold"] in ["DEFERRED_PAYMENT_ORDER", "CASH_GAP"]]
        for actual in ["DEFERRED_PAYMENT_ORDER", "CASH_GAP"]:
            rs = [r for r in critical if r["gold"] == actual]
            pair_stats.append(dict(candidate=ident, gold=actual, n=len(rs),
                                   predicted_order=sum(r["predicted"] == "DEFERRED_PAYMENT_ORDER" for r in rs),
                                   predicted_gap=sum(r["predicted"] == "CASH_GAP" for r in rs),
                                   predicted_other=sum(r["predicted"] not in ["DEFERRED_PAYMENT_ORDER", "CASH_GAP"] for r in rs),
                                   accepted=sum(r["accepted"] == "True" for r in rs),
                                   accepted_errors=sum(r["accepted"] == "True" and r["correct"] == "False" for r in rs)))
    audit = []
    for split in ["dev", "test", "examples", "human"]:
        data = read_data(split)
        for s in SLOTS + ["industry", "style"]:
            counter = Counter(r[s] if s in ["industry", "style"] else r["labels"][s] for r in data)
            for label, count in counter.items():
                audit.append(dict(split=split, field=s, label=label, n=count))
        if split in ("dev", "test"):
            for s in SLOTS:
                fixed = "OTHER" if s == "purpose" else "UNKNOWN"
                baselines.append(dict(split=split, slot=s, predicted=fixed,
                                      accuracy=sum(r["labels"][s] == fixed for r in data) / len(data),
                                      autofill_coverage=0))
    for split in ["cases", "dev", "test", "human"]:
        path = ROOT / "results" / f"amount_{split}.csv"
        if not path.exists():
            continue
        rs = read_csv(path)
        positive = [r for r in rs if r["gold"] != ""]
        filled = [r for r in rs if r["predicted"] != ""]
        parser_summaries.append(dict(split=split, n=len(rs), correct=sum(r["correct"] == "True" for r in rs),
                                     accuracy=sum(r["correct"] == "True" for r in rs) / len(rs),
                                     stated_amount_n=len(positive),
                                     stated_amount_accuracy=sum(r["correct"] == "True" for r in positive) / len(positive) if positive else None,
                                     filled_n=len(filled),
                                     extraction_precision=sum(r["correct"] == "True" for r in filled) / len(filled) if filled else None,
                                     hallucinated_amount_n=sum(r["gold"] == "" and r["predicted"] != "" for r in rs),
                                     latency_p50_s=float(np.percentile([float(r["seconds"]) for r in rs], 50)) if "seconds" in rs[0] else None,
                                     latency_p95_s=float(np.percentile([float(r["seconds"]) for r in rs], 95)) if "seconds" in rs[0] else None))
    tables = {"summary.csv": summary, "slot_metrics.csv": all_metrics, "reliability.csv": all_bins,
              "runtime.csv": all_runtime, "confusion_all_slots.csv": confusions, "errors.csv": errors,
              "thresholds.csv": thresholds, "diagnostic_risk_coverage.csv": curves,
              "critical_confusion.csv": pair_stats, "dataset_audit.csv": audit, "baselines.csv": baselines,
              "parser_summary.csv": parser_summaries, "model_artifacts.csv": artifacts}
    for file, rows in tables.items():
        if rows:
            fields = list(dict.fromkeys(k for r in rows for k in r))
            write_csv(ROOT / "results" / file, rows, fields)
    measured = [r for r in summary if r["status"] == "ok"]
    measured.sort(key=lambda r: (r["selective_accuracy_micro"] is not None and r["selective_accuracy_micro"] >= .95,
                                 r["coverage"], r["accuracy_mean"]), reverse=True)
    for r in measured:
        print(r["candidate"], "accuracy", round(r["accuracy_mean"], 4), "selective", r["selective_accuracy_micro"],
              "coverage", round(r["coverage"], 4), "p95_s", r["latency_p95_s"])


if __name__ == "__main__":
    main()
