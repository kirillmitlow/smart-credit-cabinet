# T-119. Собрать сервис mock-scenarios: модели сценария, пресеты, хранилище и API

| | |
|---|---|
| Статус | TODO |
| Владелец | Агент A/B (любой сменщик) |
| Ветка | `feat/mocks-scenarios-service` |
| Оценка | ~6 ч |
| Зависит от | [T-101](T-101-mocks-common-ids.md), [T-102](T-102-mocks-common-http.md), [T-103](T-103-mocks-common-clock-db.md), [T-104](T-104-mocks-common-idempotency.md) |
| Приоритет | M (Must) |
| Веха | V2 ([график](../02-schedule.md)) |

## Цель

Сервис «пульта» хранит описания тестовых компаний и отдаёт их по API. Здесь модели параметров сценария, пресеты и CRUD; разворачивание и раскладку по мокам делают следующие задачи.

## Входит / не входит

- **Входит:**
  - Pydantic-модели сценария из 10.2: `code`, `title`, `preset`, `expectedOutcome`, `expectedFinalOutcome`, `expectedReasonCodes[]`, `application`, `company`, `people`, `finance`, `tax`, `bankruptcies[]`, `contracts[]`, `bki.*`, `activeLoans[]`, `closedLoans[]`, `bank`, `compliance`, `raw`, `users`
  - Шесть пресетов (`IP_HEALTHY`, `LLC_HEALTHY`, `LLC_HIGH_DEBT_LOAD`, `STARTUP`, `SELF_EMPLOYED`, `PROBLEM_DEBTOR`) и `GET /api/v1/presets`
  - База `mock_scenarios` (`scenarios`, `scenario_applications`, `idempotency_keys`) и миграции, поля как в 10.7
  - `GET /api/v1/scenarios?origin=`, `GET /scenarios/{code}`, `PATCH` (Merge Patch, массивы заменяются), `DELETE` (встроенные удалять нельзя: `409 BUILTIN_SCENARIO`), `POST /scenarios` с необязательным `Idempotency-Key` (создаёт запись `PENDING`), `POST /scenarios/preview` (заглушка, наполнит [T-120](T-120-mocks-expand-identity.md))
  - Все эндпоинты требуют `X-Admin-Key`; схема безопасности `AdminKeyAuth`; блока `meta` нет
  - Параметры из 30-17: `finance.noisePercent` (0 у встроенных персон, по умолчанию ±5%) и `application.collateral.valueRub` (оценка залога); эти поля добавляются в модель и в OpenAPI
- **Не входит:**
  - Разворачивание параметров в данные ([T-120](T-120-mocks-expand-identity.md)…[T-125](T-125-mocks-expand-other-systems.md))
  - Раскладка по мокам ([T-127](T-127-mocks-apply-rollback.md))
  - Встроенные персоны ([T-131](T-131-mocks-persona-sokolova.md)…)

## Входные документы

- [Спецификация моков](../../../specs/mocks.md), разделы 10.1, 10.2, 10.4, 10.7
- [Гид по моквам](../../../mocks-guide.md), раздел «Создать свою компанию»
- [30-17 Прохождение персон](../../30-decisioning/17-persona-walkthrough.md) (оракул: точные входы и числа), раздел «Нужно внести в спецификацию моков»

## Критерии приёмки

- [ ] Модель принимает пример из 10.2 («ООО 2 года, выручка 5 млн/мес, просрочка 40 дней») и пример встроенной персоны из 10.5
- [ ] Неизвестное поле и несовместимые параметры (например, `JSC` с `founders`) дают `422` с понятным текстом
- [ ] `POST /scenarios` с тем же `Idempotency-Key` возвращает тот же `201`, второй сценарий не создаётся
- [ ] `DELETE` встроенного сценария — `409 BUILTIN_SCENARIO`
- [ ] `PATCH` склеивает объекты и заменяет массивы целиком, у встроенного ставит `modified: true`
- [ ] Тесты написаны и зелёные
- [ ] Документация и OpenAPI обновлены, если менялся контракт
- [ ] Запись в журнале
- [ ] Выполнено [определение готовности](../04-definition-of-done.md) (линтеры, PR по шаблону, статус задачи обновлён)

## Тесты

pytest с БД: CRUD, идемпотентность, `PATCH`, список по `origin`, валидация модели на шаблонах из спецификации.

## Заметки для реализации

- Модель сценария — центральный контракт, на который опираются все `expand`-задачи; названия полей не менять без решения.
- Выход `application`, `expected*` и `users` в моки не уходит — это хранится только здесь.
- Спецификация моков ещё не содержит `noisePercent` и `valueRub`: 30-17 просит внести их. Реализуем по 30-17 и пишем вопрос/правку спецификации (решение владельца спецификации), а не молча расходимся.
