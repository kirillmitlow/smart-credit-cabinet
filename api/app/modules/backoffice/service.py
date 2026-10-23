"""Чтение очереди: одна транзакция, банковское представление и курсор (T-360)."""

import base64
import binascii
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from app.modules import auth
from app.modules.backoffice import queries
from app.modules.backoffice.schemas import (
    BankCompany,
    BankQueueItem,
    BankQueuePage,
    BankReason,
    BankRecommendation,
)
from app.shared import clock, db
from app.shared.errors import AppError

_TITLES = {
    "AMOUNT_ABOVE_AUTO_LIMIT": "Сумма выше лимита автоматики",
    "COLLATERAL_REVIEW": "Нужно оценить залог",
    "GUARANTOR_REVIEW": "Нужно проверить поручителя",
    "BUSINESS_TOO_YOUNG": "Молодой бизнес",
    "MASS_REGISTRATION": "Нужна проверка регистрационных данных",
    "OVERDUE_30_89": "Просрочка от 30 до 89 дней",
    "DATA_MISMATCH": "Данные источников расходятся",
    "TURNOVER_ANOMALY": "Необычные обороты",
    "GRADE_NEEDS_REVIEW": "Риск требует ручного рассмотрения",
    "DSCR_NEAR_THRESHOLD": "Покрытие платежа близко к порогу",
    "STRESS_NEAR_THRESHOLD": "Стресс-тест близок к порогу",
    "SOURCE_UNAVAILABLE": "Источник недоступен",
    "PIPELINE_ERROR": "Обработка задержалась",
}


def require_bank(principal: auth.Principal) -> None:
    if principal.zone != auth.Zone.BANK or principal.role not in {"UNDERWRITER", "ADMIN"}:
        raise AppError(403, "FORBIDDEN", "Нужно войти как сотрудник банка")


def _cursor(value: str | None, status: str, product: str | None) -> tuple[datetime, UUID] | None:
    if value is None:
        return None
    try:
        decoded = json.loads(base64.b64decode(value, altchars=b"-_", validate=True))
        if decoded["status"] != status or decoded["product"] != product:
            raise ValueError("Курсор другого фильтра")
        at = datetime.fromisoformat(decoded["at"])
        if at.utcoffset() is None:
            raise ValueError("Время без часового пояса")
        return at, UUID(decoded["id"])
    except (ValueError, TypeError, KeyError, binascii.Error) as exc:
        raise AppError(422, "VALIDATION_ERROR", "Некорректный курсор очереди") from exc


def _encode_cursor(row: dict[str, Any], status: str, product: str | None) -> str:
    data = {
        "at": row["waiting_since"].isoformat(),
        "id": str(row["id"]),
        "status": status,
        "product": product,
    }
    return base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode()


def manual_reasons(explain: dict[str, Any], event_reason: str | None = None) -> list[BankReason]:
    codes: list[str] = []
    for step in explain.get("trace") or []:
        if step.get("step") == "11.routing":
            raw = (step.get("detail") or {}).get("manual", "")
            codes.extend(code for code in raw.split(",") if code)
    if event_reason and event_reason not in codes:
        codes.append(event_reason)
    # Снимки до trace либо технические исходы могут содержать только причины.
    if not codes:
        codes = [
            r["code"] for r in explain.get("reasons") or [] if r.get("kind") in {"FLAG", "MANUAL"}
        ]
    texts = {x["code"]: x.get("underwriter", "") for x in explain.get("explanations") or []}
    return [
        BankReason(
            code=code, title=_TITLES.get(code, "Требуется проверка"), detail=texts.get(code, "")
        )
        for code in dict.fromkeys(codes)
    ]


def _overdue(start: datetime, end: datetime) -> bool:
    # Календарь MVP: будни, без производственного календаря/часов работы банка.
    current, seconds = start.astimezone(clock.MSK), 0.0
    end = end.astimezone(clock.MSK)
    while current < end:
        boundary = (current + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        stop = min(boundary, end)
        if current.weekday() < 5:
            seconds += (stop - current).total_seconds()
            if seconds > 86_400:
                return True
        current = stop
    return False


def queue_item(row: dict[str, Any], now: datetime) -> BankQueueItem:
    explain = row["explain"] or {}
    reasons = manual_reasons(explain, row["manual_event_reason"])
    codes = {r.code for r in reasons} | set(row["flags"] or [])
    badges: list[Any] = []
    if row["version_reason"] == "INFO_PROVIDED":
        badges.append("CLIENT_ANSWERED")
    for code in ("SOURCE_UNAVAILABLE", "PIPELINE_ERROR"):
        if code in codes:
            badges.append(code)
    recommendation = explain.get("recommendation")
    return BankQueueItem(
        id=row["id"],
        number=row["number"],
        status=row["status"],
        version=row["version"],
        company=BankCompany(
            id=row["company_id"],
            name=row["company_name"],
            inn=row["inn"],
            is_bank_customer=row["is_bank_customer"],
        ),
        product_code=row["product_code"],
        amount_rub=row["amount_rub"],
        term_months=row["term_months"],
        waiting_since=row["waiting_since"],
        waiting_seconds=max(0, int((now - row["waiting_since"]).total_seconds())),
        overdue=_overdue(row["waiting_since"], now),
        manual_reasons=reasons,
        recommendation=BankRecommendation.model_validate(recommendation)
        if recommendation
        else None,
        required_level=row["required_level"],
        badges=badges,
        document_received=None,
    )


def queue(
    principal: auth.Principal, status: str, product_code: str | None, limit: int, cursor: str | None
) -> BankQueuePage:
    require_bank(principal)
    after = _cursor(cursor, status, product_code)
    with db.transaction() as session:
        rows = queries.queue_rows(
            session, status=status, product_code=product_code, after=after, limit=limit + 1
        )
        now = clock.now()
        page = rows[:limit]
        return BankQueuePage(
            items=[queue_item(row, now) for row in page],
            next_cursor=_encode_cursor(page[-1], status, product_code)
            if len(rows) > limit
            else None,
        )
