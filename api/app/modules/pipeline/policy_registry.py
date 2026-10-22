"""Версии политики (T-274, 30-13): файл → `Policy` → строка `policy_versions` по хешу.

Файл читает `pipeline`, ядро получает уже разобранные типы. Невалидный файл — `PolicyError`:
`api` не стартует. Хеш считает ядро (`policy_hash`): ключи по алфавиту, без пробелов, тексты
причин в политику не входят (Q-113). Версия фиксируется на запуске: `pipeline_runs.policy_version_id`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.decisioning import Policy, parse_policy, policy_hash
from app.modules.pipeline.models import PolicyVersion
from app.modules.pipeline.policy_loader import load_policy_file
from app.shared import clock
from app.shared.db import API_DIR
from app.shared.ids import uuid7
from app.shared.settings import get_settings

log = structlog.get_logger("app.pipeline.policy")


def policy_path() -> Path:
    path = Path(get_settings().policy_file)
    return path if path.is_absolute() else API_DIR / path


@lru_cache(maxsize=4)
def _load(path: str) -> Policy:
    return load_policy_file(path)


def current_policy() -> Policy:
    """Политика из файла `settings.policy_file`; разбирается один раз на процесс."""
    return _load(str(policy_path()))


def reset_policy_cache() -> None:
    _load.cache_clear()


def register_policy(session: Session, policy: Policy) -> PolicyVersion:
    """Найти строку по хешу или создать; повторная регистрация того же файла ничего не меняет."""
    digest = policy_hash(policy)
    session.execute(
        insert(PolicyVersion)
        .values(
            id=uuid7(),
            version=policy.meta.version,
            content_hash=digest,
            content=policy.model_dump(mode="json"),
            effective_from=policy.meta.effective_from,
            description=policy.meta.description,
            parent_hash=policy.meta.parent_hash,
            created_at=clock.now(),
        )
        .on_conflict_do_nothing(index_elements=["content_hash"])
    )
    row = session.scalars(select(PolicyVersion).where(PolicyVersion.content_hash == digest)).one()
    same_number = session.scalars(
        select(PolicyVersion.content_hash).where(
            PolicyVersion.version == policy.meta.version, PolicyVersion.content_hash != digest
        )
    ).all()
    if same_number:
        log.warning(
            "policy_version_content_changed",
            version=policy.meta.version,
            hint="число в существующем файле менять нельзя: правка = новый файл vN+1 (30-13)",
        )
    return row


def register_current(session: Session) -> PolicyVersion:
    return register_policy(session, current_policy())


def policy_by_id(session: Session, policy_version_id: UUID) -> Policy:
    """Политика, под которой стартовал запуск (содержимое из БД, а не из файла)."""
    row = session.get(PolicyVersion, policy_version_id)
    if row is None:
        raise LookupError(f"Нет версии политики {policy_version_id}")
    return parse_policy(row.content)
