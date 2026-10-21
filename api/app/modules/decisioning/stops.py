"""Семь стоп-факторов (T-289, 30-04). Автомат отказывает, только когда уверен (D-034).

Записываются все сработавшие, главным показывается первый по порядку справочника.
Недоступный источник не отменяет стоп-фактор, найденный по другим данным.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.modules.decisioning.dates import add_months
from app.modules.decisioning.loan_math import floor_rub
from app.modules.decisioning.reasons import make
from app.modules.decisioning.types import (
    ApplicantKind,
    BankruptcyCase,
    DecisionInput,
    Features,
    ReasonCode,
    SourceStatus,
    SubjectRole,
)

_STATUS_TEXT = {
    "LIQUIDATING": "в стадии ликвидации",
    "LIQUIDATED": "ликвидирована",
    "BANKRUPT": "в процедуре банкротства",
    "CEASED": "деятельность прекращена",
}
_SUBJECT_TEXT = {
    "COMPANY": "компании",
    "DIRECTOR": "руководителя",
    "FOUNDER": "учредителя",
    "GUARANTOR": "поручителя",
}
_INDUSTRY_TEXT = {
    "92": "азартные игры",
    "25.4": "производство оружия и боеприпасов",
    "64.92": "потребительское кредитование и займы",
}


def okved_matches(code: str, prefix: str) -> bool:
    """Совпадение по целым сегментам кода: «25.4» ловит 25.40, но не 25.62; «92» ловит 92.00."""
    code_parts = code.split(".")
    prefix_parts = prefix.split(".")
    if len(prefix_parts) > len(code_parts):
        return False
    for i, wanted in enumerate(prefix_parts):
        actual = code_parts[i]
        last = i == len(prefix_parts) - 1
        if (last and not actual.startswith(wanted)) or (not last and actual != wanted):
            return False
    return True


def _case_blocks(case: BankruptcyCase, today: date, window_months: int) -> date | None:
    """Дата, до которой дело мешает кредиту; `None`, если не мешает.

    Не завершено — мешает пока идёт (возвращаем `date.max`-подобную метку через today);
    завершено менее `window_months` назад — до `completed_at + window_months`.
    """
    if case.stage != "COMPLETED" or case.completed_at is None:
        return today
    until = add_months(case.completed_at, window_months)
    return until if case.completed_at > add_months(today, -window_months) else None


def _check_bankruptcy(inp: DecisionInput) -> ReasonCode | None:
    rule = inp.policy.stop_factors.bankruptcy
    today = inp.context.app_today
    snap = inp.snapshot

    def hit(subject: str, case: BankruptcyCase) -> ReasonCode | None:
        until = _case_blocks(case, today, rule.window_months)
        if until is None:
            return None
        return make(
            "BANKRUPTCY",
            subject=subject,
            subject_text=_SUBJECT_TEXT.get(subject, "участника заявки"),
            case_number=case.case_number,
            stage=case.stage,
            completed_at=case.completed_at.isoformat() if case.completed_at else None,
            apply_after=until.isoformat() if case.stage == "COMPLETED" else None,
        )

    for check in snap.bankruptcies:
        if check.meta.status != SourceStatus.OK:
            continue
        is_founder = check.role == SubjectRole.FOUNDER
        if is_founder and (
            check.share_percent is None or check.share_percent < rule.founder_share_percent
        ):
            continue
        for case in check.cases:
            found = hit(check.role.value, case)
            if found is not None:
                return found
    for subject in snap.bki:
        if subject.report is None:
            continue
        for case in subject.report.bankruptcies:
            found = hit(subject.role.value, case)
            if found is not None:
                return found
    return None


def evaluate_stop_factors(inp: DecisionInput, feats: Features) -> tuple[ReasonCode, ...]:
    cfg = inp.policy.stop_factors
    snap = inp.snapshot
    out: list[ReasonCode] = []

    # 1. Компания не действует
    reg = snap.registry
    if cfg.company_not_active.enabled and reg.meta.status == SourceStatus.OK:
        statuses = (
            cfg.company_not_active.entrepreneur_statuses
            if reg.kind == ApplicantKind.INDIVIDUAL_ENTREPRENEUR
            else cfg.company_not_active.legal_entity_statuses
        )
        if reg.status_code in statuses:
            out.append(
                make(
                    "COMPANY_NOT_ACTIVE",
                    status=reg.status_code,
                    status_text=_STATUS_TEXT.get(reg.status_code, "не действует"),
                )
            )

    # 2. Список ПОД/ФТ: компания, директор, учредитель
    if cfg.aml_list.enabled and snap.compliance.meta.status == SourceStatus.OK:
        for result in snap.compliance.results:
            if result.aml_listed:
                out.append(make("AML_LIST", subject=result.role.value))
                break

    # 3. Банкротство
    if cfg.bankruptcy.enabled:
        found = _check_bankruptcy(inp)
        if found is not None:
            out.append(found)

    # 4. Запрещённая отрасль
    if cfg.forbidden_industry.enabled and reg.okved_main:
        for prefix in cfg.forbidden_industry.okved_prefixes:
            if okved_matches(reg.okved_main, prefix):
                out.append(
                    make(
                        "FORBIDDEN_INDUSTRY",
                        okved=reg.okved_main,
                        rule=prefix,
                        industry_text=_INDUSTRY_TEXT.get(prefix, "ограниченная отрасль"),
                    )
                )
                break

    # 5. Вторая заявка в работе
    if cfg.duplicate_application.enabled and inp.context.other_active_applications:
        out.append(
            make("DUPLICATE_APPLICATION", application=inp.context.other_active_applications[0])
        )

    # 6. Налоговый долг: пени и штрафы не считаются; без выручки проверка ждёт выручку
    if (
        cfg.tax_arrears_high.enabled
        and feats.tax_known
        and feats.revenue_cautious_rub is not None
        and feats.tax_debt_rub > 0
    ):
        revenue = Decimal(feats.revenue_cautious_rub)
        allowed = revenue * cfg.tax_arrears_high.max_ratio
        if Decimal(feats.tax_debt_rub) > allowed:
            allowed_rub = floor_rub(allowed)
            out.append(
                make(
                    "TAX_ARREARS_HIGH",
                    debt_rub=feats.tax_debt_rub,
                    share=(Decimal(feats.tax_debt_rub) / revenue).quantize(Decimal("0.0001")),
                    revenue_rub=feats.revenue_cautious_rub,
                    allowed_rub=allowed_rub,
                    repay_min_rub=feats.tax_debt_rub - allowed_rub,
                )
            )

    # 7. Текущая просрочка ≥ 90 дней и ≥ 10 000 ₽ у любого оценённого субъекта
    if cfg.current_overdue_90.enabled:
        for subject in snap.bki:
            report = subject.report
            if (
                subject.meta.status == SourceStatus.OK
                and report is not None
                and report.current_overdue_days >= cfg.current_overdue_90.days
                and report.current_overdue_rub >= cfg.current_overdue_90.min_rub
            ):
                out.append(
                    make(
                        "CURRENT_OVERDUE_90",
                        subject=subject.role.value,
                        days=report.current_overdue_days,
                        overdue_rub=report.current_overdue_rub,
                    )
                )
                break
    return tuple(out)
