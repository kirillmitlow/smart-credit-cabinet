# T-257. Добавить залог и поручительство в заявку и возврат в проверку

| | |
|---|---|
| Статус | TODO |
| Владелец | не назначен (Claude Code или Codex, по очереди смен) |
| Ветка | `feat/collateral-guarantor-in-application` |
| Оценка | ~4 ч |
| Приоритет | M (Must) |
| Тонкий сквозной сценарий | нет |
| Зависит от | [T-253](T-253-application-draft.md), [T-251](T-251-application-state-machine.md), [T-222](T-222-guarantor-participant.md) |

## Цель

Клиент добавляет залог или поручителя (кейсы `stankoprom`, `quick-start`); при добавлении после встречного заявка идёт `COUNTER_OFFER → CHECKING` с новой версией.

## Входит / не входит

- **Входит:** таблица `collaterals` (`COLLATERAL`/`GUARANTEE`, описание, оценка клиента, `person_inn`, статус), `POST /applications/{id}/collaterals`; `application_versions(reason=COLLATERAL_ADDED)`, запуск `pipeline.run` по ключу версии; признаки `collateral_provided`, `guarantor_confirmed` (согласие подписано, D-082) для ядра.
- **Не входит:** подпись согласия поручителя ([T-261](T-261-consent-bundle-signing.md), [T-222](T-222-guarantor-participant.md)).

## Входные документы

- [20-02](../../20-process/02-application-states.md): Статусы заявки и переходы
- [10-06](../../10-product/06-product-catalog.md): Каталог продуктов
- [30-04](../../30-decisioning/04-stop-factors-and-flags.md): Стоп-факторы, флаги и ограничение
- [10-02](../../10-product/02-personas.md): Персоны и ожидаемые исходы

## Критерии приёмки

- [ ] `quick-start`: после принятия встречного и добавления поручителя заявка → `CHECKING` → `MANUAL_REVIEW` (при подписанном согласии)
- [ ] Без подписанного согласия поручитель не считается подтверждённым
- [ ] Двойной ввод залога не запускает конвейер дважды
- [ ] Тесты написаны и зелёные (`make check`)
- [ ] Документация и OpenAPI обновлены, если менялся контракт
- [ ] Запись в журнале

## Тесты

integration: цепочка quick-start и stankoprom на уровне API.

## Заметки для реализации

- Для ООО поручительство владельца — стандартное условие, клиенту отдельно не задаётся ([10-06](../../10-product/06-product-catalog.md)).
