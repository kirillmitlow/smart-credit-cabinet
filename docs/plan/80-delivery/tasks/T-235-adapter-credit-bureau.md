# T-235. Написать адаптер БКИ: отчёты по субъектам и сообщения

| | |
|---|---|
| Статус | TODO |
| Владелец | не назначен (Claude Code или Codex, по очереди смен) |
| Ветка | `feat/adapter-credit-bureau` |
| Оценка | ~5 ч |
| Приоритет | M (Must) |
| Тонкий сквозной сценарий | да |
| Зависит от | [T-230](T-230-resilience-layer.md), [T-260](T-260-consents-service.md), [T-112](T-112-mocks-bki-reports-consent.md), [T-113](T-113-mocks-bki-read-time-values.md), [T-114](T-114-mocks-bki-submissions.md) |

## Цель

Порт `credit_bureau`: отчёт запрашивается только с действующим согласием, ключ идемпотентности строится по заявке и субъекту, повтор безопасен.

## Входит / не входит

- **Входит:** `request_report(consent, subject, application_ref)` — сигнатура требует `consent`, без него код не вызывается (защита на уровне кода); ключ `bki-report:{заявка}:{ИНН субъекта}`; один повтор после `503` или обрыва с тем же ключом; модель `CreditHistory` (summary, просрочки, запросы без своих, банкротства, платежи, `bureauScore` только для показа); клиент `submit_event(...)` для [T-279](T-279-outbox-bureau-handlers.md) с постоянным `eventId`.
- **Не входит:** сбор по субъектам и переиспользование отчёта ([T-273](T-273-pipeline-bureau-step.md)); outbox ([T-278](T-278-outbox-relay.md)).

## Входные документы

- [50-08](../../50-architecture/08-integration-adapters.md): Адаптеры интеграций
- [50-09](../../50-architecture/09-security.md): Безопасность
- [моки, 6.1](../../../specs/mocks.md)
- [моки, 6.3](../../../specs/mocks.md)
- [20-04](../../20-process/04-consents-and-signing.md): Согласия, оферта и подпись

## Критерии приёмки

- [ ] Тест: вызов без согласия невозможен на уровне типов/сигнатуры, с просроченным — `CONSENT_EXPIRED`
- [ ] Контракт: `romashka` (просрочка 94 дня), `quick-start` (компания `NOT_FOUND`, владелец чистый), `t-overdue-45`
- [ ] `LOST_RESPONSE`: повтор возвращает тот же отчёт, в журнале `Idempotent-Replayed`, второго платного запроса нет
- [ ] Запросы `...ExcludingOwn` используются в признаках, наши запросы не считаются
- [ ] Тесты написаны и зелёные (`make check`)
- [ ] Документация и OpenAPI обновлены, если менялся контракт
- [ ] Запись в журнале

## Тесты

contract (в т.ч. chaos `LOST_RESPONSE`) + unit.

## Заметки для реализации

- `bureauScore` в решении не используется ([30-02](../../30-decisioning/02-features-catalog.md)).
