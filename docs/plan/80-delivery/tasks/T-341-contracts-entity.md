# T-341. Завести договор: `contract_uid`, хеш файла и доступ к документу

| | |
|---|---|
| Статус | TODO |
| Владелец | не назначен (Claude Code или Codex, по очереди смен) |
| Ветка | `feat/contracts-entity` |
| Оценка | ~3 ч |
| Приоритет | M (Must) |
| Тонкий сквозной сценарий | нет |
| Зависит от | [T-340](T-340-offers-variants-accept.md), [T-336](T-336-pdf-generation-weasyprint.md) |

## Цель

Принятое предложение связывается с договором: стабильный `contract_uid`, номер, хеш сохранённого файла, статусы `READY/SIGNED/CANCELLED`.

## Входит / не входит

- **Входит:** `contracts` (`variant_id`, `contract_uid`, `number`, `document_id`, `content_hash`, `status`); `GET /contracts/{id}`, `GET /contracts/{id}/document`; `contract_uid` используется АБС и БКИ (`contractUid = uid`).
- **Не входит:** подписи ([T-263](T-263-contract-signing.md)).

## Входные документы

- [50-06](../../50-architecture/06-data-model.md): Модель данных базы `api`
- [20-05](../../20-process/05-disbursement-and-after.md): Выдача и жизнь кредита после неё
- [20-04](../../20-process/04-consents-and-signing.md): Согласия, оферта и подпись

## Критерии приёмки

- [ ] Правка условий создаёт новый договор и отменяет прежний
- [ ] Чужая компания → `404`
- [ ] `contract_uid` не меняется при повторе задач
- [ ] Тесты написаны и зелёные (`make check`)
- [ ] Документация и OpenAPI обновлены, если менялся контракт
- [ ] Запись в журнале

## Тесты

integration.

## Заметки для реализации

- Поле для `contractUid` должно быть в [50-06](../../50-architecture/06-data-model.md): проверить при миграции ([20-05](../../20-process/05-disbursement-and-after.md), заметки).
