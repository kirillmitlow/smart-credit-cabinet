# T-363. Добавить запрос информации и перепроверку источников

| | |
|---|---|
| Статус | TODO |
| Владелец | не назначен (Claude Code или Codex, по очереди смен) |
| Ветка | `feat/backoffice-request-info-recheck` |
| Оценка | ~4 ч |
| Приоритет | M (Must) |
| Тонкий сквозной сценарий | нет |
| Зависит от | [T-362](T-362-backoffice-decision.md), [T-350](T-350-client-tasks-create.md), [T-277](T-277-pipeline-rerun-flows.md) |

## Цель

Андеррайтер просит документ или пояснение и возвращает заявку в проверку, если источник был недоступен (`SOURCE_UNAVAILABLE`).

## Входит / не входит

- **Входит:** `POST /backoffice/applications/{id}/request-info` (что, зачем, срок; причина, если ядро советовало иное), переход `MANUAL_REVIEW → NEEDS_INFO`; `POST …/recheck`: `MANUAL_REVIEW → CHECKING`, свежие данные без повторной покупки отчёта БКИ; «Новое с прошлого раза» после ответа клиента.
- **Не входит:** экран ([T-432](T-432-web-bank-actions.md)).

## Входные документы

- [60-04](../../60-frontend/04-backoffice-screens.md): Экраны банка: рабочее место андеррайтера
- [20-03](../../20-process/03-tasks-and-info-requests.md): Задачи клиенту: «Что нужно от вас»
- [50-07](../../50-architecture/07-api-design.md): Дизайн API
- [30-11](../../30-decisioning/11-routing-and-authority.md): Маршрут: авто или вручную, полномочия, переопределение

## Критерии приёмки

- [ ] `stankoprom`: запрос договора поставщика → ответ → снова `MANUAL_REVIEW` → `APPROVED`
- [ ] `DOWN` у БКИ → `MANUAL_REVIEW(SOURCE_UNAVAILABLE)` → восстановили → `recheck` → решение
- [ ] Тесты написаны и зелёные (`make check`)
- [ ] Документация и OpenAPI обновлены, если менялся контракт
- [ ] Запись в журнале

## Тесты

integration: цепочки stankoprom, сбой БКИ.

## Заметки для реализации

- Интерфейсы A: `pipeline.request_recheck` готов (журнал, 23.10); `applications.request_information` — в PR `feat/client-tasks`.

- Права: L1 может запрашивать информацию и перепроверять ([30-11](../../30-decisioning/11-routing-and-authority.md)).
