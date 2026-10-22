"""Заготовки после сохранения решения (T-275): предложение, задачи клиенту, outbox.

Вызываются внутри транзакции шага 6. Настоящие реализации живут в других задачах; здесь только
точки подключения, чтобы конвейер не менялся, когда они появятся.
"""

from __future__ import annotations

import structlog
from sqlalchemy.orm import Session

from app.modules.applications import Application
from app.modules.decisioning import DecisionResult
from app.modules.decisioning.types import Outcome
from app.modules.pipeline.models import Decision

log = structlog.get_logger("app.pipeline.hooks")

OFFER_OUTCOMES = frozenset({Outcome.APPROVED, Outcome.COUNTER_OFFER})


def create_offer_stub(session: Session, application: Application, decision: Decision) -> None:
    """Основа предложения для `APPROVED` и `COUNTER_OFFER`.

    TODO(T-340): создать `offers` через публичный интерфейс модуля offers (варианты из
    `decision.explain["variants"]`, срок оферты 10 дней). Пока предложения как сущности нет.
    """
    log.info("offer_stub", application=str(application.id), decision=str(decision.id))


def after_decision(
    session: Session, application: Application, decision: Decision, result: DecisionResult
) -> None:
    if result.outcome in OFFER_OUTCOMES:
        create_offer_stub(session, application, decision)
    # TODO(T-278): outbox — сообщение APPLICATION_DECIDED в БКИ, ключ уведомлений клиенту (та же транзакция)
    # TODO(T-2xx, 20-03): задача клиенту при NEEDS_INFO (`REVENUE_UNKNOWN`, `DATA_INCOMPLETE`)
