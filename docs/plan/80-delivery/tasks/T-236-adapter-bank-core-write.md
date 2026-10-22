# T-236. Написать адаптер АБС на запись: открытие счёта и выдача

| | |
|---|---|
| Статус | REVIEW — feat/api-disbursement; адаптер записи и контрактные тесты готовы, до слияния не DONE |
| Владелец | не назначен (Claude Code или Codex, по очереди смен) |
| Ветка | `feat/api-disbursement` |
| Оценка | ~3 ч |
| Приоритет | M (Must) |
| Тонкий сквозной сценарий | нет |
| Зависит от | [T-230](T-230-resilience-layer.md), [T-116](T-116-mocks-bank-core-disbursement.md), [T-117](T-117-mocks-bank-core-open-account.md) |

## Цель

Порт `bank_core` умеет открыть счёт не-клиенту и выдать кредит с ключом идемпотентности по заявке; все коды ответов АБС из [20-05](../../20-process/05-disbursement-and-after.md) разобраны.

## Входит / не входит

- **Входит:** `open_account` (ключ `acct:{заявка}`, `409 ACCOUNT_ALREADY_EXISTS` = успех), `disburse` (ключ `disb:{заявка}`); разбор ответов: `201`, `Idempotent-Replayed`, `404 CUSTOMER_NOT_FOUND`, `409 ACCOUNT_NOT_OWNED/ACCOUNT_BLOCKED/ALREADY_DISBURSED/IDEMPOTENCY_IN_PROGRESS`, `422`; чтение `customers/{inn}/loans` для сверки по `applicationRef`.
- **Не входит:** сценарий выдачи ([T-342](T-342-disbursement-workflow.md)).

## Входные документы

- [50-08](../../50-architecture/08-integration-adapters.md): Адаптеры интеграций
- [20-05](../../20-process/05-disbursement-and-after.md): Выдача и жизнь кредита после неё
- [моки, 7.3](../../../specs/mocks.md)
- [моки, 7.4](../../../specs/mocks.md)

## Критерии приёмки

- [ ] Типизированные результаты на каждый ответ АБС (таблица [20-05](../../20-process/05-disbursement-and-after.md))
- [ ] Ключ строится по заявке, а не по попытке; повторы используют тот же ключ
- [ ] Контрактный тест `garipov`: открытие счёта + выдача
- [ ] Тесты написаны и зелёные (`make check`)
- [ ] Документация и OpenAPI обновлены, если менялся контракт
- [ ] Запись в журнале

## Тесты

contract + unit; chaos `LOST_RESPONSE` проверяется в [T-343](T-343-disbursement-exactly-once.md).

## Заметки для реализации

- Автоповторов на `ACCOUNT_BLOCKED` нет: задача андеррайтеру ([20-05](../../20-process/05-disbursement-and-after.md)).
