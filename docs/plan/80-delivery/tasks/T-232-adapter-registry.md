# T-232. Написать адаптер реестра: компании, роли, банкротства

| | |
|---|---|
| Статус | TODO |
| Владелец | не назначен (Claude Code или Codex, по очереди смен) |
| Ветка | `feat/adapter-registry` |
| Оценка | ~4 ч |
| Приоритет | M (Must) |
| Тонкий сквозной сценарий | да |
| Зависит от | [T-230](T-230-resilience-layer.md), [T-107](T-107-mocks-registry-companies.md), [T-108](T-108-mocks-registry-efrsb.md) |

## Цель

Порт `registry` на языке бизнеса: `get_company(inn)`, `get_person_roles(inn)`, `get_bankruptcies(inn)` с внутренними моделями, независимыми от формата мока.

## Входит / не входит

- **Входит:** DTO под JSON мока, маппинг в `CompanyRecord`, `PersonRoles`, `BankruptcyCase`; банкротства для компании, директора и всех учредителей-людей (список субъектов собирает [T-272](T-272-pipeline-collect-sources.md)); `404` — нормальный ответ (самозанятый), а не ошибка.
- **Не входит:** автозаполнение ([T-220](T-220-company-lookup-autofill.md)); кэш ([T-237](T-237-cached-vs-fresh-gateway.md)).

## Входные документы

- [50-08](../../50-architecture/08-integration-adapters.md): Адаптеры интеграций
- [моки, 4.1](../../../specs/mocks.md)
- [моки, 4.2](../../../specs/mocks.md)
- [моки, 4.3](../../../specs/mocks.md)
- [30-04](../../30-decisioning/04-stop-factors-and-flags.md): Стоп-факторы, флаги и ограничение

## Критерии приёмки

- [ ] Контрактные тесты на живом `mock-registry` для `sokolova`, `vektor` (LIQUIDATING), `orlov` (404), `t-bankrupt`
- [ ] Недоступность → `SourceUnavailable`, в лог только замаскированный ИНН
- [ ] Код мока не импортируется
- [ ] Тесты написаны и зелёные (`make check`)
- [ ] Документация и OpenAPI обновлены, если менялся контракт
- [ ] Запись в журнале

## Тесты

contract (живые моки) + unit на respx.

## Заметки для реализации

- Поля `unreliable`, `pendingExclusion` мапятся, хотя правила по ним выключены в `v1` ([30-04](../../30-decisioning/04-stop-factors-and-flags.md)).
