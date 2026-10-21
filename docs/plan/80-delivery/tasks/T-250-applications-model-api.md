# T-250. Создать заявку: модель, миграции, `POST/GET /applications`, `allowedActions`

| | |
|---|---|
| Статус | TODO |
| Владелец | не назначен (Claude Code или Codex, по очереди смен) |
| Ветка | `feat/applications-model-api` |
| Оценка | ~5 ч |
| Приоритет | M (Must) |
| Тонкий сквозной сценарий | да |
| Зависит от | [T-201](T-201-db-and-migrations.md), [T-210](T-210-auth-sessions.md), [T-221](T-221-members-sync-from-scenarios.md), [T-202](T-202-errors-requestid-logging.md) |

## Цель

Заявка существует как сущность: создаётся черновик, читается список и карточка, ответ содержит статус и список разрешённых действий, по которому фронт строит кнопки (не по копии стейт-машины).

## Входит / не входит

- **Входит:** таблицы `applications`, `application_versions`, `application_events` (структура), `version`, человекочитаемый `number` вида `АЗ-2026-000123`; `POST /applications`, `GET /applications` (курсорная пагинация), `GET /applications/{id}`; `company_id` + фильтр по `Principal`; поле `allowedActions` (заполняется стейт-машиной [T-251](T-251-application-state-machine.md) и правами); отдельные модели ответа для клиента и банка.
- **Не входит:** переходы ([T-251](T-251-application-state-machine.md)); черновик ([T-253](T-253-application-draft.md)); отправка ([T-254](T-254-application-submit.md)).

## Входные документы

- [50-06](../../50-architecture/06-data-model.md): Модель данных базы `api`
- [20-02](../../20-process/02-application-states.md): Статусы заявки и переходы
- [50-07](../../50-architecture/07-api-design.md): Дизайн API
- [50-04](../../50-architecture/04-modules-and-boundaries.md): Модули `api` и правила зависимостей

## Критерии приёмки

- [ ] Чужая компания → `404` на все ручки (тест на двух компаниях)
- [ ] Список возвращает `{items, nextCursor}`, новые сверху
- [ ] В клиентской модели нет баллов, DSCR, снимков (контрактный тест)
- [ ] `number` уникален и читается человеком
- [ ] Тесты написаны и зелёные (`make check`)
- [ ] Документация и OpenAPI обновлены, если менялся контракт
- [ ] Запись в журнале

## Тесты

integration: создание, список, права; contract: форма ответов.

## Заметки для реализации

- Мастер создаёт заявку `DRAFT` сразу в начале ([50-06](../../50-architecture/06-data-model.md), заметки).
