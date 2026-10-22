"""Транзакционный outbox и ретранслятор «толчок + страховка» (T-278, 50-05, Q-055 вариант C).

Запись в `outbox` делается в той же транзакции, что и смена статуса: либо оба, либо ничего.
Доставляет `outbox.relay`:

* **толчок**: `enqueue_outbox` ставит `outbox.relay` после коммита, доставка почти мгновенная;
* **страховка**: beat запускает его раз в 30 с (`app/worker.py`), если толчок потерялся.

Ретранслятор берёт запись с `SELECT … FOR UPDATE SKIP LOCKED`, ставит аренду (`lease_until`) и
коммитит. Сеть вызывается вне транзакции. Умерший воркер не держит запись: аренда истекает, и её
подберёт другой. Два ретранслятора одновременно одну запись не возьмут. Порядок: запись берётся,
только если по тому же `aggregate_id` нет более ранней неотправленной (`PENDING`). Доставка «хотя бы
раз»; «ровно один раз по результату» дают ключи идемпотентности у получателя.

Shared не знает модулей: обработчики регистрируют они сами (`register_handler`). Время здесь
техническое (`clock.system_now`): аренды и паузы не должны зависеть от `APP_TODAY`.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import structlog
from sqlalchemy import func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from app.shared import clock, db
from app.shared.models import OutboxMessage
from app.shared.tasks import celery_app, enqueue

log = structlog.get_logger("app.outbox")

RELAY_TASK = "outbox.relay"
PENDING, SENT, FAILED = "PENDING", "SENT", "FAILED"

# Паузы между попытками, секунды: 5 → 15 → 45 → 2 мин → 5 мин (потолок), с разбросом ±20 %
BACKOFF_S = (5, 15, 45, 120, 300)
BACKOFF_CAP_S = 300
JITTER = 0.2
MAX_ATTEMPTS = 30
MAX_AGE = timedelta(days=1)  # мок помнит ключ 24 часа (2.7): дальше повтор уже не безопасен
LEASE = timedelta(minutes=2)  # больше самого долгого вызова (бюджет 8 с) с запасом
RELAY_BUDGET_S = 20.0  # задача укладывается в лимит 30 с (50-05)
PUSH_FLAG = "outbox_push"


@dataclass(frozen=True, slots=True)
class OutboxItem:
    """Запись, которую получает обработчик."""

    id: int
    aggregate_id: str
    event_type: str
    target_system: str
    payload: dict[str, Any]
    idempotency_key: str
    attempts: int


@dataclass(frozen=True, slots=True)
class Delivered:
    """Получатель принял сообщение (в том числе повтор с `Idempotent-Replayed`)."""


@dataclass(frozen=True, slots=True)
class Retry:
    """Сбой получателя или сети: повторить с паузой, попытка тратится."""

    error: str


@dataclass(frozen=True, slots=True)
class Defer:
    """Получатель временно закрыт (предохранитель): отложить, попытка не тратится."""

    seconds: float = 5.0
    error: str = "DEFERRED"


@dataclass(frozen=True, slots=True)
class Dead:
    """Повтор не поможет (наш дефект, решение человека): сразу `FAILED`, без автоповторов."""

    error: str


type Outcome = Delivered | Retry | Defer | Dead
type Handler = Callable[[OutboxItem], Outcome]
type DeadHook = Callable[[Session, OutboxItem, str], None]

_handlers: dict[tuple[str, str], Handler] = {}
_dead_hook: DeadHook | None = None


def register_handler(target_system: str, event_type: str, handler: Handler) -> None:
    """Модуль регистрирует доставку своего вида сообщений при старте (воркер и тесты)."""
    _handlers[(target_system, event_type)] = handler


def clear_handlers() -> None:
    _handlers.clear()


def set_dead_letter_hook(hook: DeadHook | None) -> None:
    """Что сделать в транзакции перехода в `FAILED` (запись в аудит); ставит `app/worker.py`."""
    global _dead_hook
    _dead_hook = hook


# --- запись ---------------------------------------------------------------------------------------


def enqueue_outbox(
    session: Session,
    *,
    aggregate_id: str,
    event_type: str,
    target: str,
    payload: dict[str, Any],
    idempotency_key: str,
    push: bool = True,
) -> bool:
    """Записать сообщение в транзакции вызывающего. Повтор с тем же ключом ничего не добавит.

    Возвращает `True`, если запись создана. После коммита ставится толчок `outbox.relay`.
    """
    now = clock.system_now()
    inserted = session.execute(
        insert(OutboxMessage)
        .values(
            aggregate_id=aggregate_id,
            event_type=event_type,
            target_system=target,
            payload=payload,
            idempotency_key=idempotency_key,
            status=PENDING,
            attempts=0,
            next_attempt_at=now,
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=[OutboxMessage.idempotency_key])
        .returning(OutboxMessage.id)
    ).scalar_one_or_none()
    if push and not session.info.get(PUSH_FLAG):
        session.info[PUSH_FLAG] = True
        enqueue(session, RELAY_TASK)
    return inserted is not None


# --- пауза ----------------------------------------------------------------------------------------


def backoff_delay(
    attempts: int, uniform: Callable[[float, float], float] = random.uniform
) -> float:
    """Пауза после `attempts`-й неудачной попытки: 5 с, 15 с, 45 с, 2 мин, дальше 5 мин."""
    base = BACKOFF_S[min(max(attempts, 1), len(BACKOFF_S)) - 1]
    return min(float(BACKOFF_CAP_S), base * uniform(1 - JITTER, 1 + JITTER))


# --- ретранслятор ---------------------------------------------------------------------------------


@dataclass(slots=True)
class RelayStats:
    delivered: int = 0
    retried: int = 0
    deferred: int = 0
    failed: int = 0

    @property
    def handled(self) -> int:
        return self.delivered + self.retried + self.deferred + self.failed


def _claim(session: Session) -> OutboxItem | None:
    """Взять одну готовую запись под аренду; ждущие более ранних по заявке пропускаются."""
    now = clock.system_now()
    earlier = aliased(OutboxMessage)
    keys = list(_handlers)
    if not keys:
        return None
    row = session.execute(
        select(OutboxMessage)
        .where(
            OutboxMessage.status == PENDING,
            OutboxMessage.next_attempt_at <= now,
            (OutboxMessage.lease_until.is_(None)) | (OutboxMessage.lease_until < now),
            tuple_(OutboxMessage.target_system, OutboxMessage.event_type).in_(keys),
            ~select(earlier.id)
            .where(
                earlier.aggregate_id == OutboxMessage.aggregate_id,
                earlier.id < OutboxMessage.id,
                earlier.status == PENDING,
            )
            .exists(),
        )
        .order_by(OutboxMessage.id)
        .limit(1)
        .with_for_update(skip_locked=True, of=OutboxMessage)
    ).scalar_one_or_none()
    if row is None:
        return None
    row.lease_until = now + LEASE
    session.flush()
    return OutboxItem(
        row.id,
        row.aggregate_id,
        row.event_type,
        row.target_system,
        row.payload,
        row.idempotency_key,
        row.attempts,
    )


def _deliver(item: OutboxItem) -> Outcome:
    handler = _handlers[(item.target_system, item.event_type)]
    try:
        return handler(item)
    except Exception as exc:  # noqa: BLE001 — один сбойный обработчик не должен ронять ретранслятор
        log.exception("outbox_handler_crashed", id=item.id, type=item.event_type)
        return Retry(f"HANDLER_ERROR:{type(exc).__name__}")


def _finalize(session: Session, item: OutboxItem, outcome: Outcome) -> str:
    """Записать итог доставки; возвращает итоговый статус."""
    now = clock.system_now()
    row = session.execute(
        select(OutboxMessage).where(OutboxMessage.id == item.id).with_for_update()
    ).scalar_one()
    if row.status != PENDING:  # другой ретранслятор уже закончил (аренда истекла раньше нас)
        return row.status
    row.lease_until = None
    match outcome:
        case Delivered():
            row.status, row.sent_at, row.last_error = SENT, now, None
        case Defer(seconds, error):
            row.next_attempt_at = now + timedelta(seconds=seconds)
            row.last_error = error
        case Dead(error):
            _fail(session, row, item, error)
        case Retry(error):
            row.attempts += 1
            row.last_error = error
            if row.attempts >= MAX_ATTEMPTS or now - row.created_at >= MAX_AGE:
                _fail(session, row, item, error)
            else:
                row.next_attempt_at = now + timedelta(seconds=backoff_delay(row.attempts))
    session.flush()
    return row.status


def _fail(session: Session, row: OutboxMessage, item: OutboxItem, error: str) -> None:
    row.status, row.last_error = FAILED, error
    log.error(
        "outbox_dead",
        id=row.id,
        aggregate=row.aggregate_id,
        type=row.event_type,
        attempts=row.attempts,
        error=error,
    )
    if _dead_hook is not None:
        _dead_hook(session, item, error)


def relay(budget_s: float = RELAY_BUDGET_S) -> RelayStats:
    """Доставить всё, что готово, пока есть время. Безопасно запускать параллельно и повторно."""
    stats = RelayStats()
    deadline = time.monotonic() + budget_s
    while time.monotonic() < deadline:
        with db.transaction() as session:
            item = _claim(session)
        if item is None:
            break
        outcome = _deliver(item)
        with db.transaction() as session:
            status = _finalize(session, item, outcome)
        match outcome:
            case Delivered():
                stats.delivered += 1
            case Defer():
                stats.deferred += 1
            case _ if status == FAILED:
                stats.failed += 1
            case _:
                stats.retried += 1
    return stats


def count_dead(session: Session) -> int:
    """Число записей `FAILED` (метрика `outbox_dead_total` и демо-панель)."""
    return int(
        session.execute(
            select(func.count()).select_from(OutboxMessage).where(OutboxMessage.status == FAILED)
        ).scalar_one()
    )


def retry_dead(session: Session, message_id: int) -> bool:
    """Ручной повтор `FAILED` (кнопка в демо-панели, T-365): снова в очередь с нуля."""
    now = clock.system_now()
    result = session.execute(
        update(OutboxMessage)
        .where(OutboxMessage.id == message_id, OutboxMessage.status == FAILED)
        .values(status=PENDING, attempts=0, next_attempt_at=now, created_at=now, lease_until=None)
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


@celery_app.task(name=RELAY_TASK, soft_time_limit=28, time_limit=40)  # type: ignore[untyped-decorator]
def relay_task() -> dict[str, int]:
    stats = relay()
    return {
        "delivered": stats.delivered,
        "retried": stats.retried,
        "deferred": stats.deferred,
        "failed": stats.failed,
    }
