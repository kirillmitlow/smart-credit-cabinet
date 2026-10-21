"""Record the final dev choices before allowing any held-out model inference."""
import argparse
import hashlib
import json
import time

from benchmark import code_hashes
from common import CANDIDATES, ROOT


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repeat", action="store_true")
    args = p.parse_args()
    path = ROOT / "results/evaluation_seal.json"
    if path.exists() and not args.repeat:
        raise SystemExit("Evaluation already sealed. Explicit --repeat is for reproduction only.")
    current = code_hashes()
    hashes = {}
    for c in CANDIDATES:
        file = ROOT / "results" / f"{c['id']}_settings.json"
        if file.exists():
            data = json.loads(file.read_text())
            assert data["code_hashes"] == current, f"Re-run dev with final code for {c['id']}"
            hashes[c["id"]] = hashlib.sha256(file.read_bytes()).hexdigest()
    assert hashes, "No successful dev runs"
    seal = dict(sealed_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                settings_sha256=hashes, code_hashes=current,
                dataset_manifest=json.loads((ROOT / "dataset/manifest.json").read_text()))
    path.write_text(json.dumps(seal, indent=2) + "\n")
    print("SEALED", len(hashes), "candidates. Test remains untouched until benchmark test phase.")


if __name__ == "__main__":
    main()
