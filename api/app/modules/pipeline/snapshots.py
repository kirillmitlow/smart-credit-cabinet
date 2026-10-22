"""Снимки источников: запись ответов «как есть» и чтение их обратно для сборки входа (T-272).

Запись неизменяема и идемпотентна: ключ `run + ресурс + ИНН субъекта`, повтор шага не создаёт
дубль (`ON CONFLICT DO NOTHING`). Недоступный источник тоже получает строку (`UNAVAILABLE` и
причина): по ней после обрыва запуска видно, что именно не ответило, а не «не спрашивали».
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.decisioning.types import SourceStatus
from app.modules.integrations import Ok, Result, SourceUnavailable, parse_snapshot
from app.modules.pipeline import facts
from app.modules.pipeline.models import SourceSnapshot
from app.shared import clock
from app.shared.ids import uuid7

# Отчёт БКИ переиспользуется в пределах заявки до 30 дней (D-077)
BKI_REUSE_WINDOW = timedelta(days=30)
CONSENT_ERROR_PREFIX = "CONSENT_"


@dataclass(frozen=True, slots=True)
class Collected:
    """Результат одного вызова адаптера до записи в базу."""

    resource: str
    subject_inn: str
    result: Result[Any]

    @property
    def unavailable(self) -> bool:
        return isinstance(self.result, SourceUnavailable)


def _canonical(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def payload_hash(payload: object) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def to_row(run_id: UUID, application_id: UUID, item: Collected) -> dict[str, Any]:
    result = item.result
    if isinstance(result, Ok):
        meta = result.snapshot_meta
        found = result.data is not None
        payload: Any = result.raw if found and result.raw is not None else {}
        status = "OK" if found else "NOT_FOUND"
        system, retrieved = meta.system.value, meta.retrieved_at
        actual, request_id = meta.data_actual_at, meta.request_id
    else:
        payload = {
            "reason": result.reason.value,
            "errorCode": result.error_code,
            "statusCode": result.status_code,
            "attempts": result.attempts,
        }
        status, system = "UNAVAILABLE", result.system.value
        retrieved, actual, request_id = clock.system_now(), None, None
    return {
        "id": uuid7(),
        "run_id": run_id,
        "application_id": application_id,
        "system": system,
        "resource": item.resource,
        "subject_inn": item.subject_inn,
        "status": status,
        "payload": payload,
        "payload_hash": payload_hash(payload),
        "data_actual_at": actual,
        "retrieved_at": retrieved,
        "request_id": request_id,
    }


def save_snapshots(
    session: Session, run_id: UUID, application_id: UUID, items: list[Collected]
) -> int:
    """Записать снимки; возвращает, сколько новых строк появилось (повтор шага даёт 0)."""
    created = 0
    for item in items:
        stmt = (
            insert(SourceSnapshot)
            .values(**to_row(run_id, application_id, item))
            .on_conflict_do_nothing(constraint="uq_source_snapshots_run_resource_subject")
            .returning(SourceSnapshot.id)
        )
        if session.execute(stmt).first() is not None:
            created += 1
    return created


def find_reusable_report(
    session: Session, application_id: UUID, subject_inn: str
) -> SourceSnapshot | None:
    """Свежий отчёт БКИ по субъекту из этой заявки (любой запуск), не старше 30 дней."""
    since = clock.system_now() - BKI_REUSE_WINDOW
    return session.scalars(
        select(SourceSnapshot)
        .where(
            SourceSnapshot.application_id == application_id,
            SourceSnapshot.resource == facts.BKI_REPORT,
            SourceSnapshot.subject_inn == subject_inn,
            SourceSnapshot.status == "OK",
            SourceSnapshot.retrieved_at >= since,
        )
        .order_by(SourceSnapshot.retrieved_at.desc())
        .limit(1)
    ).first()


def _record(row: SourceSnapshot) -> facts.SourceRecord:
    status = SourceStatus(row.status)
    data = None
    error_code = None
    if status == SourceStatus.OK:
        data = parse_snapshot(
            row.resource, row.payload, inn=row.subject_inn, on=row.retrieved_at.date()
        )
    elif status == SourceStatus.UNAVAILABLE and isinstance(row.payload, dict):
        error_code = row.payload.get("errorCode")
    return facts.SourceRecord(
        resource=row.resource,
        subject_inn=row.subject_inn,
        status=status,
        snapshot_id=str(row.id) if status != SourceStatus.UNAVAILABLE else None,
        data_as_of=row.data_actual_at or row.retrieved_at.date(),
        data=data,
        error_code=error_code,
    )


def load_records(session: Session, run_id: UUID, application_id: UUID) -> facts.Records:
    """Ответы источников запуска + свежие отчёты БКИ этой заявки (в том числе из прошлых запусков)."""
    own = list(session.scalars(select(SourceSnapshot).where(SourceSnapshot.run_id == run_id)))
    records = [_record(r) for r in own]
    have = {(r.resource, r.subject_inn) for r in records}
    older = session.scalars(
        select(SourceSnapshot.subject_inn)
        .where(
            SourceSnapshot.application_id == application_id,
            SourceSnapshot.resource == facts.BKI_REPORT,
            SourceSnapshot.status == "OK",
            SourceSnapshot.run_id != run_id,
        )
        .distinct()
    ).all()
    for inn in older:
        if (facts.BKI_REPORT, inn) in have:
            continue
        reusable = find_reusable_report(session, application_id, inn)
        if reusable is not None:
            records.append(_record(reusable))
    return facts.Records(records)
