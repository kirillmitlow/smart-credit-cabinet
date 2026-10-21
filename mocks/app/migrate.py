"""Миграции роли из командной строки (для разработчика).

Пример:
    DATABASE_URL=... uv run python -m app.migrate registry revision --autogenerate -m "companies"
    DATABASE_URL=... uv run python -m app.migrate registry upgrade
"""

from __future__ import annotations

import argparse
import os

from alembic import command

from app.common.db import alembic_config
from app.settings import Role


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=[r.value for r in Role])
    sub = parser.add_subparsers(dest="cmd", required=True)
    rev = sub.add_parser("revision")
    rev.add_argument("-m", "--message", required=True)
    rev.add_argument("--autogenerate", action="store_true")
    sub.add_parser("upgrade")
    args = parser.parse_args()

    cfg = alembic_config(Role(args.role), os.environ.get("DATABASE_URL"))
    if args.cmd == "revision":
        command.revision(cfg, message=args.message, autogenerate=args.autogenerate)
    else:
        command.upgrade(cfg, "head")


if __name__ == "__main__":
    main()
