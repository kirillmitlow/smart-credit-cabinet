# T-286. Рассчитать признаки БКИ, налогов, компании и текущей нагрузки

| | |
|---|---|
| Статус | DONE |
| Владелец | не назначен (Claude Code или Codex, по очереди смен) |
| Ветка | `feat/features-bureau-tax-company` |
| Оценка | ~5 ч |
| Приоритет | M (Must) |
| Тонкий сквозной сценарий | да |
| Зависит от | [T-280](T-280-decide-types-and-purity.md), [T-281](T-281-policy-schema-v1.md) |

## Цель

Признаки, нужные стоп-факторам, скоркарте и лимитам: кредитная история по каждому субъекту, класс истории, налоговый долг, возраст бизнеса, клиент банка, платежи и общий долг без двойного счёта.

## Входит / не входит

- **Входит:** по субъектам `company/director/guarantor`: `has_history`, `history_months`, `overdue_now_days/rub` (учитывается при ≥ 10 000 ₽), `overdue_max_24m_days`, `restructurings_24m`, `inquiries_30d`, `rejected_90d` (только «без своих»), `bankruptcies`; `credit_history_class` — худший класс по всем субъектам (`CLEAN` … `PAST_90`); у компании без истории не выше `THIN_CLEAN`; определение классов по предложению [30-17](../../30-decisioning/17-persona-walkthrough.md): `CLEAN` — нет просрочек, обязательств ≥ 2, история ≥ 24 мес.; `THIN_CLEAN` — нет просрочек, но обязательств < 2 или история < 24 мес.; `tax_debt_rub`, `tax_debt_ratio`, пени, правонарушения, `risk_mass_*`, `net_profit_rub`, `interest_paid_rub`; `business_age_months`, `is_bank_customer`, `customer_tenure_months`, `tax_regime`, `sme_category`, `form_matches_registry` (нормализация ФИО отдельной чистой функцией); `existing_payments_rub`, `total_debt_rub` (+50% условных обязательств), `debt_to_revenue`, `coverage_existing` — наши кредиты в АБС и БКИ объединяются по `contractUid = uid`, кредит не считается дважды; `collateral_provided`, `guarantor_confirmed`, `security_confirmed`.
- **Не входит:** выручка и поток ([T-285](T-285-features-revenue-cashflow.md)); антифрод ([T-288](T-288-features-consistency-antifraud.md)).

## Входные документы

- [30-02](../../30-decisioning/02-features-catalog.md): Каталог признаков
- [30-04](../../30-decisioning/04-stop-factors-and-flags.md): Стоп-факторы, флаги и ограничение
- [30-18](../../30-decisioning/18-economic-assumptions.md): Реестр экономических параметров и источников

## Критерии приёмки

- [ ] Тест: кредит, присутствующий и в АБС, и в БКИ, считается один раз
- [ ] Нет данных БКИ в режиме PREVIEW → осторожные значения (30-07), не ноль
- [ ] Таблица ФИО (ё/е, «Иванов И. И.», лишние пробелы) проходит
- [ ] `bureauScore` бюро в решении не используется
- [ ] Каждый признак имеет тесты «типичный случай / граница / нет данных»
- [ ] Тесты написаны и зелёные (`make check`)
- [ ] Документация и OpenAPI обновлены, если менялся контракт
- [ ] Запись в журнале

## Тесты

unit по каждому признаку; property: монотонность INV-02, INV-03 на уровне признаков.

## Заметки для реализации

- Просрочка меньше 10 000 ₽ — техническая, не учитывается (допущение по Базелю CRE36.69, [30-02](../../30-decisioning/02-features-catalog.md)).
