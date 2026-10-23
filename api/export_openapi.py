"""Deterministic API and five mock schemas, without starting services or connecting to databases."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from app.main import create_app
from app.shared.settings import Settings

ROOT = Path(__file__).resolve().parent.parent


def schemas() -> dict[str, dict]:
    api = create_app(Settings(app_env="local")).openapi()
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("Install uv to export mock schemas")
    # A separate process keeps the two distinct packages named `app` isolated.
    result = subprocess.run(  # noqa: S603 — fixed source and repository-owned project path
        [
            uv,
            "run",
            "--directory",
            str(ROOT / "mocks"),
            "python",
            "-c",
            "import json; from app.main import create_app; "
            "from app.settings import ROLE_SERVICE, Settings; "
            "print(json.dumps({str(name): create_app(Settings(mock_role=role, database_url=None)).openapi() "
            "for role, name in ROLE_SERVICE.items()}, ensure_ascii=False))",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    mocks = json.loads(result.stdout)
    return {
        "api.openapi.json": api,
        **{f"{name}.openapi.yaml": spec for name, spec in mocks.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Report stale schemas without writing")
    args = parser.parse_args()
    changed = []
    for name, spec in schemas().items():
        path = ROOT / "docs" / "api" / name
        # JSON is valid YAML and preserves the existing scenarios contract's representation.
        content = json.dumps(spec, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            changed.append(name)
            if not args.check:
                path.write_text(content, encoding="utf-8")
    if args.check and changed:
        print("OpenAPI differs from code; run make openapi: " + ", ".join(changed))
        return 1
    print("OpenAPI: all six schemas match code" if args.check else "OpenAPI: exported six schemas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
