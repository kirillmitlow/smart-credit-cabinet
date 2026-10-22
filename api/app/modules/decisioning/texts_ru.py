"""Справочник текстов `texts/ru` (T-298, 30-12): клиенту, андеррайтеру, «что можно сделать».

Ядро возвращает код с параметрами, тексты собираются здесь в момент решения и сохраняются в
снимке (Q-113, D-091): поправка опечатки не требует новой версии правил и не меняет старые
решения. Тексты в хеш политики не входят. Клиенту не показываем слова «грейд», «балл», «скоринг»,
«PD», «DSCR», «стоп-фактор», «флаг»; отказ по `AML_LIST` причину не раскрывает.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from app.modules.decisioning.types import Explanation, FactorScore, ParamValue, ReasonCode

if TYPE_CHECKING:
    from app.modules.decisioning.scoring import ScoreResult

_NBSP = " "
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_PERCENT_KEYS = {"share", "pd", "shock", "p_def12"}
SOON = "Обычно до 1 рабочего дня"


@dataclass(frozen=True, slots=True)
class TextEntry:
    client: str
    underwriter: str
    action: str
    params: tuple[str, ...] = ()
    client_visible: bool = True


# ---------------------------------------------------------------- форматирование


def format_money(rub: int) -> str:
    """1150000 → «1 150 000 ₽» (неразрывные пробелы)."""
    grouped = f"{abs(rub):,}".replace(",", _NBSP)
    return f"{'-' if rub < 0 else ''}{grouped}{_NBSP}₽"


def format_decimal(value: Decimal, places: int = 3) -> str:
    quant = Decimal(1).scaleb(-places)
    text = f"{value.quantize(quant, rounding=ROUND_HALF_UP):f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


def format_percent(value: Decimal) -> str:
    return format_decimal(value * 100, 2) + "%"


def format_value(key: str, value: ParamValue) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, Decimal):
        return format_percent(value) if key in _PERCENT_KEYS else format_decimal(value)
    if isinstance(value, int):
        return format_money(value) if key.endswith("_rub") else str(value)
    match = _DATE_RE.match(value)
    if match:
        return f"{match.group(3)}.{match.group(2)}.{match.group(1)}"
    return value


def _fill(template: str, params: dict[str, ParamValue]) -> str:
    def sub(match: re.Match[str]) -> str:
        key = match.group(1)
        return format_value(key, params[key]) if key in params else "—"

    return re.sub(r"\{(\w+)\}", sub, template)


# ---------------------------------------------------------------- фразы вклада факторов (30-12)

FACTOR_CLIENT_PHRASES: dict[str, str] = {
    "SC_AGE": "бизнесу пока немного лет",
    "SC_CREDIT_HISTORY": "в кредитной истории есть просрочки или она короткая",
    "SC_INQUIRIES": "недавно вы подавали много заявок в другие банки",
    "SC_DEBT_LOAD": "действующие долги велики по сравнению с выручкой",
    "SC_TREND": "выручка снижается",
    "SC_VOLATILITY": "выручка сильно скачет по месяцам",
    "SC_TAX": "есть задолженность по налогам",
    "SC_CLIENT": "вы пока недавно или не обслуживаетесь у нас",
    "SC_COVERAGE": "текущие платежи по кредитам занимают большую часть свободных денег",
}


def top_deficit_phrases(score: ScoreResult, limit: int = 3) -> str:
    """До трёх самых больших недоборов фразами для клиента (недобор > 50% максимума)."""
    bad = [f for f in score.factors if f.max_points and f.deficit * 2 > f.max_points]
    bad.sort(key=lambda f: (-f.deficit, f.factor))
    return "; ".join(FACTOR_CLIENT_PHRASES[f.factor] for f in bad[:limit]) or "общая картина"


FACTOR_HELPED_PHRASES: dict[str, str] = {
    "SC_CREDIT_HISTORY": "чистая кредитная история",
    "SC_VOLATILITY": "стабильная выручка",
    "SC_TAX": "нет долгов по налогам",
    "SC_COVERAGE": "текущие платежи вам по силам",
    "SC_CLIENT": "вы давно обслуживаетесь у нас",
    "SC_INQUIRIES": "вы не подавали много заявок в другие банки",
    "SC_DEBT_LOAD": "небольшие долги по сравнению с выручкой",
    "SC_TREND": "выручка растёт",
    "SC_AGE": "бизнес работает достаточно давно",
}  # порядок = важность для клиента: первыми идут фразы про историю и стабильность
HELPED_LIMIT = 2
AFFECTED_LIMIT = 3


def client_factor_phrases(factors: Sequence[FactorScore]) -> dict[str, list[str]]:
    """Что помогло (до 2, только почти полный балл) и что повлияло (до 3 недоборов) — клиенту.

    Тексты считаются в момент решения и хранятся в снимке (Q-113): через месяц клиент видит то же.
    """
    by_name = {f.factor: f for f in factors}
    helped = [
        FACTOR_HELPED_PHRASES[name]
        for name in FACTOR_HELPED_PHRASES
        if name in by_name
        and by_name[name].max_points
        and by_name[name].points * 10 >= by_name[name].max_points * 8
    ]
    bad = [f for f in factors if f.max_points and f.deficit * 2 > f.max_points]
    bad.sort(key=lambda f: (-f.deficit, f.factor))
    return {
        "whatHelped": helped[:HELPED_LIMIT],
        "whatAffected": [FACTOR_CLIENT_PHRASES[f.factor] for f in bad[:AFFECTED_LIMIT]],
    }


# ---------------------------------------------------------------- справочник

TEXTS: dict[str, TextEntry] = {
    "SELF_EMPLOYED": TextEntry(
        "Вы зарегистрированы как самозанятый. Кредиты для бизнеса мы даём ИП и компаниям",
        "В ЕГРИП записи нет, ФНС подтверждает статус плательщика НПД",
        "Зарегистрироваться как ИП (онлайн, в ФНС) и подать заявку снова",
    ),
    "DATA_INCOMPLETE": TextEntry(
        "Не хватает данных: {todo}. Заполните их, чтобы мы продолжили",
        "Не заполнено: {fields}; не подписаны согласия: {consents}",
        "Заполнить и подписать согласия",
        ("todo", "fields", "consents"),
    ),
    "REVENUE_UNKNOWN": TextEntry(
        "Мы не видим, сколько денег приходит в ваш бизнес. Загрузите выписку по счёту из другого банка",
        "Нет оборотов в банке, свежей отчётности и выписки. Проверены: {checked}",
        "Загрузить выписку (формат 1С) минимум за 6, лучше за 12 месяцев",
        ("checked",),
    ),
    "COLLATERAL_REQUIRED": TextEntry(
        "Для такой суммы нужен залог — гарантия для банка",
        "{product}: сумма {amount_rub} больше порога {threshold_rub}, залог обязателен",
        "Добавить залог или уменьшить сумму до {threshold_rub}",
        ("product", "amount_rub", "threshold_rub"),
    ),
    # --- стоп-факторы
    "COMPANY_NOT_ACTIVE": TextEntry(
        "По данным реестра компания не действует ({status_text}). Кредит даём только действующему бизнесу",
        "ЕГРЮЛ/ЕГРИП: статус {status}",
        "Если данные устарели, обновить их в ФНС и подать заявку снова",
        ("status", "status_text"),
    ),
    "AML_LIST": TextEntry(
        "Не можем предложить кредит по внутренним правилам банка",
        "Совпадение со списком ПОД/ФТ, субъект {subject}. Клиенту причину не раскрывать (115-ФЗ)",
        "Обратиться в отделение банка",
        ("subject",),
    ),
    "BANKRUPTCY": TextEntry(
        "В публичном реестре есть сведения о банкротстве {subject_text}. Кредит выдать не можем",
        "ЕФРСБ/БКИ: {subject}, дело {case_number}, стадия {stage}, завершено {completed_at}",
        "Подать заявку после {apply_after}, если дело завершено",
        ("subject", "subject_text", "case_number", "stage", "completed_at", "apply_after"),
    ),
    "FORBIDDEN_INDUSTRY": TextEntry(
        "Бизнес в сфере «{industry_text}» мы не кредитуем",
        "Главный ОКВЭД {okved} в списке запрещённых (правило {rule})",
        "Если основной вид деятельности указан неверно, обновить его в ЕГРЮЛ",
        ("okved", "rule", "industry_text"),
    ),
    "DUPLICATE_APPLICATION": TextEntry(
        "У вас уже есть заявка №{application} в работе",
        "Другая заявка компании в работе: {application}",
        "Дождаться решения или отозвать прежнюю заявку",
        ("application",),
    ),
    "TAX_ARREARS_HIGH": TextEntry(
        "У вас есть долг по налогам {debt_rub}: это больше десятой части месячной выручки. "
        "Сначала погасите его",
        "Недоимка ЕНС {debt_rub} = {share} выручки {revenue_rub} в месяц (порог 10%)",
        "Погасить хотя бы {repay_min_rub} (останется не более {allowed_rub}); "
        "заявка подаётся заново, решение за минуты",
        ("debt_rub", "share", "revenue_rub", "allowed_rub", "repay_min_rub"),
    ),
    "CURRENT_OVERDUE_90": TextEntry(
        "По кредиту есть просрочка больше трёх месяцев. Пока она есть, новый кредит выдать не можем",
        "БКИ, субъект {subject}: просрочка {days} дн., {overdue_rub}",
        "Погасить просрочку и подать заявку заново",
        ("subject", "days", "overdue_rub"),
    ),
    # --- флаги и ограничение
    "MASS_REGISTRATION": TextEntry(
        f"Заявку смотрит специалист. {SOON}",
        "ФНС: {which} в списке массовых",
        "Запросить пояснение и документы по месту нахождения",
        ("which",),
    ),
    "OVERDUE_30_89": TextEntry(
        f"Заявку смотрит специалист. Если по кредиту есть просрочка, погасите её: решение будет "
        f"быстрее. {SOON}",
        "Просрочка {days} дн., {overdue_rub}, субъект {subject}",
        "Запросить подтверждение погашения",
        ("days", "overdue_rub", "subject"),
    ),
    "DATA_MISMATCH": TextEntry(
        "Мы нашли расхождение в данных. Специалист уточнит его в заявке",
        "{kind}: {a} против {b}, расхождение {share} (порог 30%)",
        "Запросить выписку или пояснение",
        ("kind", "a", "b", "share"),
    ),
    "TURNOVER_ANOMALY": TextEntry(
        f"Заявку смотрит специалист. {SOON}",
        "Правило «{rule}»: {details}",
        "Запросить договоры и закрывающие документы",
        ("rule", "details"),
    ),
    "SOURCE_UNAVAILABLE": TextEntry(
        "Часть проверок задерживается. Заявку возьмёт специалист, от вас ничего не нужно",
        "Недоступно: {sources}",
        "Нажать «Перепроверить источники»",
        ("sources",),
    ),
    "PIPELINE_ERROR": TextEntry(
        "Обработка задержалась. Заявку возьмёт специалист",
        "Конвейер упал {attempts} раз, запуск {run_id}",
        "Перепроверить; сообщить разработчикам",
        ("attempts", "run_id"),
    ),
    "BUSINESS_TOO_YOUNG": TextEntry(
        "Вашему бизнесу меньше {required_months} месяцев. Без обеспечения кредит дать не можем, "
        "с поручительством владельца или залогом — рассмотрим",
        "Возраст {age_months} мес., обеспечение: {security}",
        "Добавить поручителя или залог, либо подать заявку позже",
        ("required_months", "age_months", "security"),
    ),
    # --- деньги
    "DSCR_LOW": TextEntry(
        "Платёж {payment_rub} в месяц тяжёл для вашего бизнеса: безопасно можно платить до "
        "{safe_payment_rub}",
        "Поток {flow_rub}, текущие платежи {existing_rub}, новый {payment_rub}, "
        "DSCR {dscr} < {threshold}",
        "Выбрать меньшую сумму, больший срок или другой продукт",
        ("payment_rub", "safe_payment_rub", "flow_rub", "existing_rub", "dscr", "threshold"),
    ),
    "STRESS_DSCR_LOW": TextEntry(
        "Если выручка упадёт на {shock}, платить будет тяжело. Предлагаем условия с запасом",
        "Шок {shock}: DSCR {stress_dscr} < {threshold}. Ставится при DSCR ≥ 1,25; "
        "по вероятностному стрессу — P_def12 {p_def12}",
        "Выбрать меньшую сумму, больший срок или другой продукт",
        ("shock", "stress_dscr", "threshold", "p_def12"),
    ),
    "DEBT_TOO_HIGH": TextEntry(
        "Общий долг вместе с новым кредитом больше годовой выручки",
        "Долг {debt_rub} + новый {new_rub} = {share} годовой выручки {revenue_rub} (порог 100%)",
        "Уменьшить сумму до {max_new_rub} или погасить часть долгов",
        ("debt_rub", "new_rub", "share", "revenue_rub", "max_new_rub"),
    ),
    "LIMIT_ABOVE_CAP": TextEntry(
        "Для этого продукта лимит не может быть выше {cap_rub}",
        "Правило {rule}: запрошено {requested_rub}, предел {cap_rub}",
        "Лимит не выше {cap_rub}",
        ("rule", "requested_rub", "cap_rub"),
    ),
    # --- правила продукта
    "PRODUCT_AGE_MIN": TextEntry(
        "Этот кредит доступен бизнесу старше {required_months} мес. Вашему — {age_months}",
        "Продукт {product}: возраст {age_months} < {required_months}",
        "Другой продукт или заявка после {available_from}",
        ("product", "required_months", "age_months", "available_from"),
    ),
    "NOT_BANK_CLIENT": TextEntry(
        "Овердрафт доступен клиентам банка с оборотами за {required_months} месяцев",
        "Клиент: {is_client}, месяцев оборотов {turnover_months}",
        "Открыть счёт; пока подойдёт экспресс-кредит",
        ("is_client", "turnover_months", "required_months"),
    ),
    "GRADE_NOT_ALLOWED": TextEntry(
        "По этому продукту сейчас не одобрим. Посмотрите другие варианты",
        "Грейд {grade}: {product} недоступен ({why})",
        "Выбрать вариант из встречных",
        ("grade", "product", "why"),
    ),
    "CONTRACT_INVALID": TextEntry(
        "Контракт не подходит: {reason_text}",
        "№ {registry_number}: статус {status}, срок оплаты {payment_deadline}, оплачено {paid_rub}",
        "Выбрать другой контракт",
        ("reason_text", "registry_number", "status", "payment_deadline", "paid_rub"),
    ),
    "AMOUNT_OUT_OF_RANGE": TextEntry(
        "Сумма и срок должны быть в границах продукта: {amount_min_rub} – {amount_max_rub}, "
        "{term_min_months}–{term_max_months} мес.",
        "Запрос {amount_rub} / {term_months} мес. вне каталога ({product})",
        "Изменить значения",
        (
            "amount_min_rub",
            "amount_max_rub",
            "term_min_months",
            "term_max_months",
            "amount_rub",
            "term_months",
            "product",
        ),
    ),
    # --- маршрут и итог
    "AMOUNT_ABOVE_AUTO_LIMIT": TextEntry(
        f"Для такой суммы заявку рассматривает специалист. {SOON}",
        "Сумма {amount_rub} > авто-лимита {limit_rub} (грейд {grade})",
        "Приложить документы, чтобы ускорить",
        ("amount_rub", "limit_rub", "grade"),
    ),
    "COLLATERAL_REVIEW": TextEntry(
        "Специалист оценит залог и может попросить документы",
        "Залог: {description}, оценка клиента {value_rub}, к сумме {share}",
        "Договор или счёт продавца, отчёт об оценке",
        ("description", "value_rub", "share"),
    ),
    "GRADE_NEEDS_REVIEW": TextEntry(
        f"Заявку смотрит специалист. {SOON}",
        "Грейд {grade}, {points} баллов, PD {pd}",
        "—",
        ("grade", "points", "pd"),
    ),
    "NEAR_THRESHOLD": TextEntry(
        f"Заявку смотрит специалист. {SOON}",
        "{metric} {value} в серой зоне {zone_from}–{zone_to}",
        "—",
        ("metric", "value", "zone_from", "zone_to"),
    ),
    "RISK_TOO_HIGH": TextEntry(
        "По итогам проверки кредит одобрить не можем. Что повлияло больше всего: {factors}",
        "Грейд E, {points} баллов. Вклад факторов — в таблице решения",
        "Улучшить указанное и подать заявку снова",
        ("factors", "points"),
    ),
    "NO_OFFER_FOUND": TextEntry(
        "Сейчас денежный поток не позволяет безопасно обслужить даже самый небольшой кредит",
        "Минимум {amount_rub} на {term_months} мес.: платёж {payment_rub} не проходит порог "
        "встречных (DSCR ≥ 1,30, стресс ≥ 1,05)",
        "Подтвердить выручку выпиской, добавить залог или поручителя",
        ("amount_rub", "term_months", "payment_rub"),
    ),
    "GRADE_CAPPED": TextEntry(
        "",
        "Грейд ограничен потолком {cap}: {because}",
        "—",
        ("cap", "because"),
        client_visible=False,
    ),
}


def render(reason: ReasonCode) -> Explanation:
    """Три текста по одному коду: параметры подставлены, числа и даты отформатированы."""
    entry = TEXTS[reason.code]
    params = reason.params
    return Explanation(
        code=reason.code,
        client=_fill(entry.client, params) if entry.client_visible else "",
        underwriter=_fill(entry.underwriter, params),
        action=_fill(entry.action, params),
    )
