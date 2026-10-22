# T-340. Создать предложение и варианты, принятие и отказ

| | |
|---|---|
| Статус | DONE — PR feat/api-offer-signing; варианты встречных ждут T-297 (`variantsStatus = PENDING`); вариант с залогом/поручителем → 409 `SECURITY_REQUIRED` до T-257; `APPROVED` в БКИ (Q-022) не отправляется |
| Владелец | не назначен (Claude Code или Codex, по очереди смен) |
| Ветка | `feat/offers-variants-accept` |
| Оценка | ~6 ч |
| Приоритет | M (Must) |
| Тонкий сквозной сценарий | нет |
| Зависит от | [T-275](T-275-decision-persistence.md), [T-251](T-251-application-state-machine.md), [T-282](T-282-money-annuity-schedule.md) |

## Цель

Решение `APPROVED` или `COUNTER_OFFER` порождает предложение банка с вариантами; клиент выбирает вариант и принимает или отказывается.

## Входит / не входит

- **Входит:** `offers` (`AS_REQUESTED/COUNTER`, срок 10 дней), `offer_variants` (до 3: продукт, сумма, срок, ставка, платёж, переплата, обеспечение, `recommended`, `what_changed`); `GET /applications/{id}/offer`, `POST /offers/{id}/accept` (вариант, `Idempotency-Key`), `POST /offers/{id}/decline`; переходы `APPROVED/COUNTER_OFFER → OFFER_ACCEPTED/WITHDRAWN`; запуск генерации документов; выбранный контракт ЕИС для `CONTRACT`; принятие встречного шлёт `APPROVED` в БКИ (Q-022).
- **Не входит:** генерация PDF ([T-336](T-336-pdf-generation-weasyprint.md)); подпись ([T-263](T-263-contract-signing.md)).

## Входные документы

- [20-04](../../20-process/04-consents-and-signing.md): Согласия, оферта и подпись
- [20-02](../../20-process/02-application-states.md): Статусы заявки и переходы
- [30-10](../../30-decisioning/10-counter-offer-options.md): Варианты: как строим встречные предложения
- [50-06](../../50-architecture/06-data-model.md): Модель данных базы `api`
- [50-07](../../50-architecture/07-api-design.md): Дизайн API

## Критерии приёмки

- [ ] Платёж на карточке варианта = платёж в графике = калькулятор (единый вызов)
- [ ] Принять истёкшее предложение нельзя (`409`)
- [ ] Двойное принятие создаёт один переход и один запуск генерации
- [ ] Вариант с обеспечением, которого нет, ведёт `COUNTER_OFFER → CHECKING` ([T-257](T-257-collateral-guarantor-in-application.md))
- [ ] Тесты написаны и зелёные (`make check`)
- [ ] Документация и OpenAPI обновлены, если менялся контракт
- [ ] Запись в журнале

## Тесты

integration: accept/decline, гонка, истечение.

## Заметки для реализации

- Слово «оферта» в интерфейсе — «предложение банка»; ПСК не показываем ([20-04](../../20-process/04-consents-and-signing.md)).
