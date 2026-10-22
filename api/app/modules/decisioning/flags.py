"""Флаги (T-288, T-290, 30-04): подозрение или нехватка данных → `MANUAL_REVIEW`, отказа нет (D-034).

Четыре флага ядра: `MASS_REGISTRATION`, `OVERDUE_30_89`, `DATA_MISMATCH`, `TURNOVER_ANOMALY`.
Признаки (сверки, накачка, транзит, число плательщиков) считает `features.py`; здесь они только
сравниваются с порогами `policy.flags`. Какое именно правило сработало и с какими числами —
в параметрах причины: по ним андеррайтер видит, что проверять (30-12).

`SOURCE_UNAVAILABLE` формирует `eligibility.unavailable_sources`; `PIPELINE_ERROR` ядро не
выдаёт: его пишет сторож `pipeline`, когда прогон не завершился (30-04).

Маршрут принимает список флагов на входе (`routing.route`) и сам переводит заявку человеку: стоп-факторы
и `NEEDS_INFO` сильнее флагов, флаги сильнее условного встречного молодому бизнесу.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.decisioning.policy import Policy
from app.modules.decisioning.reasons import make
from app.modules.decisioning.stops import okved_matches
from app.modules.decisioning.texts_ru import format_decimal, format_money, format_percent
from app.modules.decisioning.types import (
    Comparison,
    DecisionInput,
    Features,
    ReasonCode,
    SourceStatus,
)


def _mass_registration(feats: Features, policy: Policy) -> list[ReasonCode]:
    if not policy.flags.mass_registration.enabled:
        return []
    which = [
        text
        for hit, text in (
            (feats.risk_mass_address, "адрес"),
            (feats.risk_mass_director, "руководитель"),
            (feats.risk_mass_founder, "учредитель"),
        )
        if hit
    ]
    return [make("MASS_REGISTRATION", which=", ".join(which))] if which else []


def _overdue_30_89(inp: DecisionInput) -> list[ReasonCode]:
    """Просрочка от `min_days` у любого оценённого субъекта, кроме той, что уже стоп-фактор."""
    rule = inp.policy.flags.overdue_30_89
    if not rule.enabled:
        return []
    stop = inp.policy.stop_factors.current_overdue_90
    worst: tuple[int, int, str] | None = None
    for subject in inp.snapshot.bki:
        report = subject.report
        if subject.meta.status != SourceStatus.OK or report is None:
            continue
        days, rub = report.current_overdue_days, report.current_overdue_rub
        if days < rule.min_days or rub < rule.min_rub:
            continue
        if stop.enabled and days >= stop.days and rub >= stop.min_rub:
            continue  # это стоп-фактор, не флаг: между ними нет дня-щели (30-04)
        if worst is None or (days, rub) > worst[:2]:
            worst = (days, rub, subject.role.value)
    if worst is None:
        return []
    return [make("OVERDUE_30_89", days=worst[0], overdue_rub=worst[1], subject=worst[2])]


# ---------------------------------------------------------------- DATA_MISMATCH


def _share_mismatch(
    rule_id: str, kind: str, comparison: Comparison | None, limit: Decimal
) -> ReasonCode | None:
    """Расхождение больше `limit` от знаменателя: ровно на пороге флага нет."""
    if comparison is None or comparison.deviation <= limit:
        return None
    return make(
        "DATA_MISMATCH",
        rule=rule_id,
        kind=kind.format(year=comparison.year),
        a=format_money(comparison.a_rub),
        b=format_money(comparison.b_rub),
        metric=f"расхождение {format_percent(comparison.deviation)} (порог {format_percent(limit)})",
        value=comparison.deviation,
        year=comparison.year,
    )


def _data_mismatch(feats: Features, policy: Policy) -> list[ReasonCode]:
    rules = policy.flags.data_mismatch
    out: list[ReasonCode | None] = []
    if rules.turnover_vs_financials.enabled:
        out.append(
            _share_mismatch(
                "TURNOVER_VS_FINANCIALS",
                "Обороты за {year} г. без НДС и отчётность (стр. 2110)",
                feats.mismatch_turnover_fin,
                rules.turnover_vs_financials.max_share,
            )
        )
    if rules.declared_vs_calculated.enabled:
        out.append(
            _share_mismatch(
                "DECLARED_VS_CALCULATED",
                "Заявленная выручка в месяц и расчётная (без НДС)",
                feats.mismatch_declared,
                rules.declared_vs_calculated.max_share,
            )
        )
    if rules.statement_vs_financials.enabled:
        out.append(
            _share_mismatch(
                "STATEMENT_VS_FINANCIALS",
                "Выписка клиента за {year} г. и отчётность (стр. 2110)",
                feats.mismatch_statement,
                rules.statement_vs_financials.max_share,
            )
        )
    ratio = feats.flow_crosscheck_ratio
    floor = rules.flow_crosscheck
    if (
        floor.enabled
        and ratio is not None
        and ratio < floor.min_ratio
        and feats.flow_observed_rub is not None
        and feats.flow_model_rub is not None
    ):
        out.append(
            make(
                "DATA_MISMATCH",
                rule="FLOW_CROSSCHECK",
                kind="Поток по счёту и поток модели в месяц",
                a=format_money(feats.flow_observed_rub),
                b=format_money(feats.flow_model_rub),
                metric=(
                    f"отношение {format_decimal(ratio, 2)} "
                    f"(порог не ниже {format_decimal(floor.min_ratio, 2)})"
                ),
                value=ratio,
                year=None,
            )
        )
    return [r for r in out if r is not None]


def _director_mismatch(inp: DecisionInput, feats: Features) -> list[ReasonCode]:
    if not inp.policy.flags.data_mismatch.director_vs_registry.enabled:
        return []
    if feats.form_matches_registry:
        return []
    return [
        make(
            "DATA_MISMATCH",
            rule="DIRECTOR_VS_REGISTRY",
            kind="Директор в анкете и в реестре",
            a=inp.application.director_name_in_form or "—",
            b=inp.snapshot.registry.director_name or "—",
            metric="ФИО не совпали",
            value=None,
            year=None,
        )
    ]


# ---------------------------------------------------------------- TURNOVER_ANOMALY


def _pump(feats: Features, policy: Policy) -> ReasonCode | None:
    cfg = policy.flags.turnover_anomaly.pump
    pump = feats.pump
    if not cfg.enabled or pump is None:
        return None
    if pump.ratio < cfg.min_ratio or pump.modified_z < cfg.min_modified_z:
        return None
    # Сезонное исключение: годом ранее те же месяцы уже были выше своей базы (30-02)
    if pump.prior_year_ratio is not None and pump.prior_year_ratio >= cfg.seasonal_repeat_ratio:
        return None
    return make(
        "TURNOVER_ANOMALY",
        rule="PUMP",
        rule_text="накачка оборотов",
        details=(
            f"средний оборот за последние {cfg.recent_months} мес. {format_money(pump.recent_rub)} "
            f"против обычных {format_money(pump.base_rub)} (×{format_decimal(pump.ratio, 2)}), "
            f"z = {format_decimal(pump.modified_z, 2)}"
        ),
        recent_rub=pump.recent_rub,
        base_rub=pump.base_rub,
        ratio=pump.ratio,
        modified_z=pump.modified_z,
    )


def _transit(feats: Features, policy: Policy) -> ReasonCode | None:
    cfg = policy.flags.turnover_anomaly.transit
    months = feats.transit_months
    if not cfg.enabled or months is None or months < cfg.min_months:
        return None
    return make(
        "TURNOVER_ANOMALY",
        rule="TRANSIT",
        rule_text="транзит",
        details=(
            f"списания не меньше {format_percent(cfg.min_outgoing_share)} поступлений "
            f"в {months} из {cfg.window_months} мес."
        ),
        months=months,
    )


def _single_payer(inp: DecisionInput, feats: Features) -> ReasonCode | None:
    cfg = inp.policy.flags.turnover_anomaly.single_payer
    payers, average = feats.payers_in_6m_max, feats.payers_in_6m_avg_income_rub
    if not cfg.enabled or payers is None or average is None:
        return None
    # Эквайринг и СБП: у розницы и услуг населению «плательщиков» мало по природе (10.3 моков)
    okved = inp.snapshot.registry.okved_main
    if okved and any(okved_matches(okved, prefix) for prefix in cfg.exempt_okved_prefixes):
        return None
    if payers > cfg.max_payers or average < cfg.min_avg_income_rub:
        return None
    return make(
        "TURNOVER_ANOMALY",
        rule="SINGLE_PAYER",
        rule_text="один плательщик",
        details=(
            f"не больше {payers} контрагентов в каждом из последних {cfg.window_months} мес. "
            f"при средних поступлениях {format_money(average)} в месяц"
        ),
        payers=payers,
        average_income_rub=average,
    )


def _turnover_anomaly(inp: DecisionInput, feats: Features) -> list[ReasonCode]:
    found = (_pump(feats, inp.policy), _transit(feats, inp.policy), _single_payer(inp, feats))
    return [r for r in found if r is not None]


# ---------------------------------------------------------------- точка входа


def evaluate_flags(inp: DecisionInput, feats: Features) -> tuple[ReasonCode, ...]:
    """Сработавшие флаги ядра. Порядок: как в 30-04, внутри `DATA_MISMATCH` — как в таблице."""
    return (
        *_mass_registration(feats, inp.policy),
        *_overdue_30_89(inp),
        *_data_mismatch(feats, inp.policy),
        *_director_mismatch(inp, feats),
        *_turnover_anomaly(inp, feats),
    )
