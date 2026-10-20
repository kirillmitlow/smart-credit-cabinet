import csv
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema.json").read_text())
SLOTS = list(SCHEMA)
LABELS = {s: list(SCHEMA[s]) for s in SLOTS}
CANDIDATES = json.loads((ROOT / "candidates.json").read_text())


def read_data(split):
    path = ROOT / "dataset" / f"{split}.jsonl"
    if split != "human":
        expected = json.loads((ROOT / "dataset/manifest.json").read_text())[path.name]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected["sha256"], "Corpus changed"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for r in rows:
        assert isinstance(r["text"], str) and r["text"].strip()
        assert all(r["labels"][s] in LABELS[s] for s in SLOTS)
        assert r["labels"]["amount_rub"] is None or isinstance(r["labels"]["amount_rub"], int)
    return rows


def gold(rows, slot):
    return np.array([LABELS[slot].index(r["labels"][slot]) for r in rows])


def softmax(x, temperature=1):
    x = np.asarray(x, dtype=np.float64) / temperature
    x = x - x.max(axis=-1, keepdims=True)
    x = np.exp(x)
    return x / x.sum(axis=-1, keepdims=True)


def write_csv(path, rows, fields=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def model_path(candidate):
    return ROOT / "models" / candidate["repo"].replace("/", "--")
