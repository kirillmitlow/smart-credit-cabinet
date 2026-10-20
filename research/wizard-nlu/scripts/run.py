"""Serial orchestration keeps CPU latency measurements free of competing model runs."""
import argparse
import csv
import json
import subprocess
import sys
import time

from common import CANDIDATES, ROOT, model_path, write_csv


def main():
    p = argparse.ArgumentParser()
    p.add_argument("phase", choices=["dev", "test", "human"])
    p.add_argument("--ids", nargs="*")
    p.add_argument("--rerun-dev", action="store_true")
    p.add_argument("--repeat", action="store_true", help="Reproduce an already recorded run explicitly")
    args = p.parse_args()
    results = []
    for c in CANDIDATES:
        if args.ids and c["id"] not in args.ids:
            continue
        ready = model_path(c) / "download-sha256.json"
        wait_started = time.monotonic()
        while not ready.exists() and time.monotonic() - wait_started < 1200:
            print("Waiting for download:", c["id"], flush=True)
            time.sleep(15)
        if not ready.exists():
            results.append(dict(candidate=c["id"], phase=args.phase, status="skipped",
                                seconds=time.monotonic() - wait_started, reason="Download not ready after 20 minutes"))
            continue
        executable = ROOT / ("modern/.venv/bin/python" if c["kind"] in ("llm35", "gliner") else ".venv/bin/python")
        command = [str(executable), "-u", str(ROOT / "scripts/benchmark.py"), args.phase, "--id", c["id"]]
        if args.repeat or (args.phase == "dev" and args.rerun_dev):
            command.append("--allow-repeat")
        log = ROOT / "results" / f"log-{c['id']}-{args.phase}.txt"
        print("RUN", args.phase, c["id"], flush=True)
        started = time.monotonic()
        try:
            with log.open("w") as out:
                child = subprocess.Popen(command, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT)
                timeout_reason = None
                while child.poll() is None:
                    elapsed = time.monotonic() - started
                    ready = "MODEL_READY" in log.read_text(errors="replace")
                    # Fine-tuning is work, not model startup; its individual loads are tiny.
                    if elapsed > 1200 and not ready and c["kind"] != "finetuned":
                        timeout_reason = "Model startup/first inference exceeded 20 minutes"
                    if elapsed > 3600:
                        timeout_reason = "Whole phase exceeded one-hour research budget"
                    if timeout_reason:
                        child.kill()
                        child.wait()
                        break
                    time.sleep(2)
            status = "skipped" if timeout_reason else "ok" if child.returncode == 0 else "failed"
            reason = timeout_reason or ("" if child.returncode == 0 else log.read_text()[-2500:])
        except subprocess.TimeoutExpired:
            status, reason = "skipped", "Whole phase exceeded one-hour research budget"
        results.append(dict(candidate=c["id"], phase=args.phase, status=status,
                            seconds=time.monotonic() - started, reason=reason))
        write_csv(ROOT / "results" / f"status_{args.phase}.csv", results)
        print(status.upper(), c["id"], round(results[-1]["seconds"], 1), reason[:350], flush=True)
    if results:
        write_csv(ROOT / "results" / f"status_{args.phase}.csv", results)


if __name__ == "__main__":
    main()
