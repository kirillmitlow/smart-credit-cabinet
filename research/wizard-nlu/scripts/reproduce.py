"""Complete research replay. Explicit --repeat preserves the one-pass default guard."""
import argparse
import subprocess
import sys

from common import ROOT


def run(command):
    subprocess.run(command, cwd=ROOT, check=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ids", nargs="*")
    p.add_argument("--repeat", action="store_true", help="Overwrite local copies of published measured outputs")
    args = p.parse_args()
    ids = ["--ids", *args.ids] if args.ids else []
    run(["uv", "sync", "--project", "modern", "--frozen"])
    run([sys.executable, "scripts/download.py", *ids])
    run([sys.executable, "scripts/checks.py"])
    run([sys.executable, "scripts/checks.py", "--split", "dev"])
    suffix = ["--repeat"] if args.repeat else []
    run([sys.executable, "scripts/run.py", "dev", *ids, *suffix])
    run([sys.executable, "scripts/seal.py", *(["--repeat"] if args.repeat else [])])
    run([sys.executable, "scripts/run.py", "test", *ids, *suffix])
    run([sys.executable, "scripts/checks.py", "--split", "test"])
    run([sys.executable, "scripts/aggregate.py"])
    run([sys.executable, "scripts/audit_results.py"])
    run([sys.executable, "scripts/report_tables.py"])


if __name__ == "__main__":
    main()
