"""Таблицы конвейера (50-06): запуски, снимки источников, версии политики, решения и причины.

Снимки, решения и причины неизменяемы: триггер БД запрещает UPDATE и DELETE (D-030).
Строка `pipeline_runs` меняется (аренда, контрольная точка), это служебная таблица.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared import clock
from app.shared.db import Base, IdMixin

RUN_STATUSES = ("QUEUED", "RUNNING", "DONE", "FAILED")
SNAPSHOT_STATUSES = ("OK", "NOT_FOUND", "UNAVAILABLE")
DECISION_SOURCES = ("ENGINE", "UNDERWRITER")
DECISION_OUTCOMES = ("APPROVED", "COUNTER_OFFER", "NEEDS_INFO", "MANUAL_REVIEW", "REJECTED")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class PipelineRun(IdMixin, Base):
    """Один запуск конвейера на версию заявки; `run_key` = версия + причина, поэтому уникален.

    `current_step` — код последнего выполненного шага (контрольная точка); `lease_token` и
    `locked_until` — аренда от двойного исполнения (50-05).
    """

    __tablename__ = "pipeline_runs"
    __table_args__ = (
        UniqueConstraint("run_key", name="uq_pipeline_runs_run_key"),
        CheckConstraint(f"status IN ({_in(RUN_STATUSES)})", name="status"),
    )

    application_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    version_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("application_versions.id"))
    run_key: Mapped[str] = mapped_column(String(80))
    trigger: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="QUEUED")
    current_step: Mapped[str | None] = mapped_column(String(32))
    policy_version_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("policy_versions.id"))
    lease_token: Mapped[UUID | None] = mapped_column(Uuid)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PolicyVersion(IdMixin, Base):
    """Реестр версий правил: файл `policy/vN.yaml` регистрируется по хешу канонической формы."""

    __tablename__ = "policy_versions"
    __table_args__ = (UniqueConstraint("content_hash", name="uq_policy_versions_content_hash"),)

    version: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    effective_from: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text)
    parent_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)


class SourceSnapshot(IdMixin, Base):
    """Ответ источника как есть. Для недоступного источника — причина (`status = UNAVAILABLE`)."""

    __tablename__ = "source_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "resource", "subject_inn", name="uq_source_snapshots_run_resource_subject"
        ),
        CheckConstraint(f"status IN ({_in(SNAPSHOT_STATUSES)})", name="status"),
        Index("ix_source_snapshots_application_resource", "application_id", "resource"),
    )

    run_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("pipeline_runs.id"), index=True)
    application_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("applications.id", ondelete="CASCADE")
    )
    system: Mapped[str] = mapped_column(String(16))
    resource: Mapped[str] = mapped_column(String(32))
    subject_inn: Mapped[str] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict[str, Any] | list[Any]] = mapped_column(JSONB)
    payload_hash: Mapped[str] = mapped_column(String(64))
    data_actual_at: Mapped[date | None] = mapped_column(Date)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    request_id: Mapped[str | None] = mapped_column(String(64))


class Decision(IdMixin, Base):
    """Снимок решения (D-030): по `inputs` и политике `decide()` даёт тот же результат."""

    __tablename__ = "decisions"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_decisions_run_id"),
        CheckConstraint(f"source IN ({_in(DECISION_SOURCES)})", name="source"),
        CheckConstraint(f"outcome IN ({_in(DECISION_OUTCOMES)})", name="outcome"),
    )

    application_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("pipeline_runs.id"))
    source: Mapped[str] = mapped_column(String(16), default="ENGINE")
    outcome: Mapped[str] = mapped_column(String(16))
    route: Mapped[str] = mapped_column(String(8))
    required_level: Mapped[str] = mapped_column(String(2))
    policy_version_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("policy_versions.id"))
    engine_version: Mapped[str] = mapped_column(String(64))
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB)
    inputs_hash: Mapped[str] = mapped_column(String(64))
    features: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    score: Mapped[int | None] = mapped_column(Integer)
    grade: Mapped[str | None] = mapped_column(String(1))
    pd: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    revenue_monthly_rub: Mapped[int | None] = mapped_column(BigInteger)
    free_cash_flow_rub: Mapped[int | None] = mapped_column(BigInteger)
    dscr: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    stress_dscr: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    max_amount_rub: Mapped[int | None] = mapped_column(BigInteger)
    rate_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    payment_rub: Mapped[int | None] = mapped_column(BigInteger)
    # Весь результат ядра (числа, варианты, след, тексты причин): тексты сохраняются в снимке (Q-113)
    explain: Mapped[dict[str, Any]] = mapped_column(JSONB)
    snapshot_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid))
    overrides_decision_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("decisions.id"))
    override_reason: Mapped[str | None] = mapped_column(Text)  # комментарий андеррайтера
    # Только UNDERWRITER (миграция 0011): кто решил, его уровень, код причины, отклонение от ядра
    actor_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    actor_level: Mapped[str | None] = mapped_column(String(2))
    override_reason_code: Mapped[str | None] = mapped_column(String(32))
    deviation: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)


class DecisionReason(Base):
    """Код причины: по строке на код; `position` хранит порядок (первый — главный)."""

    __tablename__ = "decision_reasons"
    __table_args__ = (
        UniqueConstraint("decision_id", "position", name="uq_decision_reasons_position"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    decision_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("decisions.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))
    points: Mapped[int | None] = mapped_column(Integer)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
