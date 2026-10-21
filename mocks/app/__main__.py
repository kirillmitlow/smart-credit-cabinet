"""Точка входа контейнера: `python -m app`.

Один процесс на контейнер: режим chaos живёт в памяти процесса (раздел 3.1).
"""

from __future__ import annotations

import sys

import uvicorn

from app.chaos import ServerSendShim
from app.common.middleware import configure_logging
from app.main import create_app
from app.settings import ConfigError, load_settings


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    configure_logging(settings.service_name)
    uvicorn.run(
        ServerSendShim(create_app(settings)),
        host="0.0.0.0",  # noqa: S104 — слушаем внутри контейнера, наружу порт публикует compose
        port=8000,
        workers=1,
        log_config=None,
        proxy_headers=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
