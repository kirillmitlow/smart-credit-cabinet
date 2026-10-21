"""Public model metadata and resumable curl downloads; never calls inference APIs."""
import argparse
import fnmatch
import hashlib
import json
import pathlib
import subprocess
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]


def api(url):
    # curl uses the system trust store (some macOS Python installs lack CA roots).
    return json.loads(subprocess.check_output(
        ["curl", "-fsSL", "--retry", "2", "--connect-timeout", "20", "--max-time", "90", url], timeout=100))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ids", nargs="*")
    p.add_argument("--metadata-only", action="store_true")
    args = p.parse_args()
    candidates = json.loads((ROOT / "candidates.json").read_text())
    manifest_file = ROOT / "model_manifest.json"
    manifest = json.loads(manifest_file.read_text()) if manifest_file.exists() else {}
    for c in candidates:
        if args.ids and c["id"] not in args.ids:
            continue
        started = time.monotonic()
        repo = c["repo"]
        try:
            if repo not in manifest:
                data = api("https://huggingface.co/api/models/" + repo)
                manifest[repo] = {
                    "revision": data["sha"],
                    "license": data.get("cardData", {}).get("license", "UNSPECIFIED"),
                    "checked_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "files": [f["rfilename"] for f in data["siblings"]],
                    "source": "https://huggingface.co/" + repo,
                }
                manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            info = manifest[repo]
            print(c["id"], info["revision"], info["license"], flush=True)
            if args.metadata_only:
                print(info["files"], flush=True)
                continue
            dest = ROOT / "models" / repo.replace("/", "--")
            dest.mkdir(parents=True, exist_ok=True)
            has_safe = any(f.endswith(".safetensors") for f in info["files"])
            patterns = ["*.json", "*.safetensors", "*.txt", "*.model", "*.jinja", "LICENSE*", "README.md"]
            if not has_safe:
                patterns.append("pytorch_model.bin")
            selected = [f for f in info["files"] if any(fnmatch.fnmatch(f, pat) for pat in patterns)
                        and not f.startswith(("onnx/", "openvino/", "onnx_", "assets/", "eval/"))]
            for f in selected:
                target = dest / f
                if target.exists():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                partial = target.with_name(target.name + ".partial")
                remaining = 1200 - (time.monotonic() - started)
                if remaining <= 0:
                    raise TimeoutError("20 minute candidate download budget exceeded")
                url = f"https://huggingface.co/{repo}/resolve/{info['revision']}/{f}"
                cmd = ["curl", "-fL", "--retry", "3", "--retry-delay", "2", "--connect-timeout", "20",
                       "--speed-limit", "1024", "--speed-time", "60", "--max-time", str(int(remaining)),
                       "-C", "-", "-o", str(partial), url]
                print("Downloading", c["id"], f, flush=True)
                subprocess.run(cmd, check=True, timeout=remaining + 5, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
                partial.rename(target)
            hashes = {}
            for f in dest.rglob("*"):
                if f.is_file() and not f.name.endswith(".partial"):
                    digest = hashlib.sha256()
                    with f.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                            digest.update(chunk)
                    hashes[str(f.relative_to(dest))] = digest.hexdigest()
            (dest / "download-sha256.json").write_text(json.dumps(hashes, indent=2) + "\n")
            print("READY", c["id"], round(time.monotonic() - started, 1), flush=True)
        except Exception as e:
            print("FAILED", c["id"], repr(e), flush=True)
            status = ROOT / "results" / "download_failures.jsonl"
            with status.open("a") as out:
                out.write(json.dumps({"id": c["id"], "error": repr(e), "seconds": time.monotonic() - started}) + "\n")


if __name__ == "__main__":
    main()
