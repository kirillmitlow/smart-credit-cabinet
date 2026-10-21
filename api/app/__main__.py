"""Точка входа контейнера: `python -m app`. Неверная конфигурация — выход с понятным сообщением."""

from __future__ import annotations

import sys

import uvicorn
from pydantic import ValidationError

from app.shared.settings import get_settings


def main() -> int:
    try:
        get_settings()
    except ValidationError as exc:
        reasons = "; ".join(str(e["msg"]) for e in exc.errors())
        print(f"api не запущен: {reasons}", file=sys.stderr)
        return 2
    uvicorn.run("app.main:build", factory=True, host="0.0.0.0", port=8000, log_config=None)  # noqa: S104
    return 0


if __name__ == "__main__":
    sys.exit(main())
