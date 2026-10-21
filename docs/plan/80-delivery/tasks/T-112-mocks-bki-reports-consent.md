# T-112. Реализовать mock-credit-bureau: хранилище и запрос отчёта с проверкой согласия 🧠

| | |
|---|---|
| Статус | TODO |
| Владелец | Агент A/B; 🧠 кандидат для GPT-6 Astra |
| Ветка | `feat/mocks-bki-reports-consent` |
| Оценка | ~6 ч |
| Зависит от | [T-101](T-101-mocks-common-ids.md), [T-102](T-102-mocks-common-http.md), [T-103](T-103-mocks-common-clock-db.md), [T-104](T-104-mocks-common-idempotency.md), [T-105](T-105-mocks-admin-api.md) |
| Приоритет | M (Must) |
| Веха | V2 ([график](../02-schedule.md)) |

## Цель

Основа БКИ: субъекты, обязательства, запросы и заявки, запрос отчёта `POST credit-reports` с проверкой пяти причин отказа по согласию. Каждый запрос оставляет след.

## Входит / не входит

- **Входит:**
  - База `mock_bki` (`subjects`, `obligations`, `inquiries`, `applications_info`, `bankruptcies`, `reports`, `submissions`, `idempotency_keys`) и миграции; `AdminHandler` с телом `subject`, `obligations[]`, `inquiries[]`, `applications[]`, `bankruptcies[]`
  - `POST /api/v1/credit-reports`: субъект ищется по ИНН (тип должен подходить к длине ИНН), согласие проверяется по порядку `CONSENT_MISSING` → `CONSENT_SUBJECT_MISMATCH` → `CONSENT_NOT_YET_VALID` (допуск 5 минут) → `CONSENT_EXPIRED` → `CONSENT_PURPOSE_MISMATCH`
  - Запрос всегда пишется в `inquiries`, в том числе при `NOT_FOUND`; отчёт целиком сохраняется в `reports`
  - `matchStatus: NOT_FOUND` с `summary` из нулей; необязательный `Idempotency-Key` (повтор возвращает тот же `reportId` и не пишет второй запрос)
- **Не входит:**
  - Значения, считаемые при чтении (в [T-113](T-113-mocks-bki-read-time-values.md))
  - `GET credit-reports/{id}` (в [T-113](T-113-mocks-bki-read-time-values.md))
  - `POST submissions` (в [T-114](T-114-mocks-bki-submissions.md))

## Входные документы

- [Спецификация моков](../../../specs/mocks.md), разделы 6, 6.1 (запрос, проверка согласия), 6.4 (хранение), 8.3 (`mock-credit-bureau`)

## Критерии приёмки

- [ ] Каждая из пяти причин `403` даёт свой `code`; тест на допуск ±5 минут вокруг границы
- [ ] Повторный запрос с тем же `Idempotency-Key` и телом не добавляет запись в `inquiries`; без ключа каждый запрос новый
- [ ] Субъект типа `LEGAL_ENTITY` с 12-значным ИНН отклоняется `422`
- [ ] `NOT_FOUND` возвращает `200`, пишет запрос и содержит все поля `summary` нулями, не `null`
- [ ] Согласие хранится вместе с отчётом; ИНН в логах маскируется
- [ ] Тесты написаны и зелёные
- [ ] Документация и OpenAPI обновлены, если менялся контракт
- [ ] Запись в журнале
- [ ] Выполнено [определение готовности](../04-definition-of-done.md) (линтеры, PR по шаблону, статус задачи обновлён)

## Тесты

pytest с БД: пять отказов по согласию, `NOT_FOUND`, идемпотентный повтор, тип субъекта против ИНН, запись запроса. Параллельный повтор — на уровне [T-104](T-104-mocks-common-idempotency.md).

## Заметки для реализации

- Не считать `summary` при записи: он вычисляется при чтении ([T-113](T-113-mocks-bki-read-time-values.md)). Здесь важно закрепить, какие поля хранятся (даты и периоды), а какие нет.
- Допуск 5 минут и «сегодня» берутся только из `common/clock.py`.
