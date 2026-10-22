"""Доступ к политике для каталога, мастера и согласий (10-06, 10-07, 30-13).

Файл `policy/vN.yaml` разбирает ядро (`decisioning.parse_policy`); здесь только чтение с диска и
кэш. Загрузчик `pipeline` стоит выше по графу модулей и сюда не доступен (50-04), поэтому читаем
сами: десять строк, один источник правды — тот же файл и та же схема.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.modules.decisioning import Policy, PolicyError, parse_policy
from app.shared.settings import get_settings

API_DIR = Path(__file__).resolve().parents[3]


def policy_path() -> Path:
    path = Path(get_settings().policy_file)
    return path if path.is_absolute() else API_DIR / path


def policy_dir() -> Path:
    """Каталог рядом с файлом политики: там же лежат `consents/*` (тексты согласий)."""
    return policy_path().parent


@lru_cache(maxsize=4)
def _load(path: Path) -> Policy:
    try:
        data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PolicyError(f"не удалось прочитать политику {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PolicyError(f"политика {path}: ожидался словарь верхнего уровня")
    return parse_policy(data)


def get_policy() -> Policy:
    """Действующая политика (файл из `POLICY_FILE`)."""
    return _load(policy_path())


def clear_cache() -> None:
    _load.cache_clear()
