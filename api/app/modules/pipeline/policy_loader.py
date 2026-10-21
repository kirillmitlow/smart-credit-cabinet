"""Чтение файла политики `policy/vN.yaml` (T-281, 30-13): файл читает pipeline, не ядро.

Ядро получает уже разобранные типы. Невалидный файл (нет `source` у числа, дыра в грейдах,
`float` вместо строки) — `PolicyError`: `api` не стартует. Версионирование, хеш и таблица
`policy_versions` — отдельная задача (T-274).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.modules.decisioning import Policy, PolicyError, parse_policy


def load_policy_file(path: str | Path) -> Policy:
    """Файл → `Policy`. Ошибки чтения и разбора YAML тоже приходят как `PolicyError`."""
    try:
        text = Path(path).read_text(encoding="utf-8")
        data: Any = yaml.safe_load(text)
    except (OSError, yaml.YAMLError) as exc:
        raise PolicyError(f"не удалось прочитать политику {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PolicyError(f"политика {path}: ожидался словарь верхнего уровня")
    return parse_policy(data)
