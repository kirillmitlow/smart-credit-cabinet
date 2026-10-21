# T-370. Реализовать демо-API: персоны, сбои моков и вход для тестов

| | |
|---|---|
| Статус | TODO |
| Владелец | не назначен (Claude Code или Codex, по очереди смен) |
| Ветка | `feat/demo-api-core` |
| Оценка | ~4 ч |
| Приоритет | M (Must) |
| Тонкий сквозной сценарий | нет |
| Зависит от | [T-213](T-213-bank-demo-login.md), [T-200](T-200-api-skeleton.md), [T-105](T-105-mocks-admin-api.md), [T-106](T-106-mocks-chaos.md), [T-119](T-119-mocks-scenarios-service.md), [T-129](T-129-mocks-resync-reset.md), [T-221](T-221-members-sync-from-scenarios.md) |

## Цель

Модуль `demo` (только при `DEMO_MODE`) отдаёт шпаргалку по персонам и переключает сбои моков; это единственное исключение из «api не вызывает админ-API моков» (D-081).

## Входит / не входит

- **Входит:** гейт `DEMO_MODE`, иначе `403 DEMO_MODE_DISABLED` на все `/demo/*`; `GET /demo/personas` (данные из `mock-scenarios`: что просит, ожидаемый исход и коды, что дальше) без кнопки входа; `GET /demo/chaos`, `PUT /demo/chaos/{system}` (прокси на `PUT /admin/chaos`); `POST /demo/personas/{code}/login` — только хелпер интеграционных тестов при `DEMO_MODE`; `POST /demo/scenarios` — создание тестовой компании.
- **Не входит:** сброс ([T-371](T-371-demo-reset-all.md), [T-372](T-372-demo-reset-persona.md)); выписка ([T-373](T-373-demo-bank-statement.md)).

## Входные документы

- [50-07](../../50-architecture/07-api-design.md): Дизайн API
- [60-05](../../60-frontend/05-demo-panel.md): Демо-панель
- [50-08](../../50-architecture/08-integration-adapters.md): Адаптеры интеграций
- [00-05](../../00-meta/05-decisions-index.md): Реестр решений

## Критерии приёмки

- [ ] `DEMO_MODE=false`: ни одна демо-ручка не работает
- [ ] Список персон не придумывается панелью, а берётся из сценариев
- [ ] Админ-ключи моков в ответах не появляются
- [ ] Тесты написаны и зелёные (`make check`)
- [ ] Документация и OpenAPI обновлены, если менялся контракт
- [ ] Запись в журнале

## Тесты

integration: гейт, прокси сбоев (заглушки).

## Заметки для реализации

- Не распространять исключение на рабочее место банка ([50-09](../../50-architecture/09-security.md)).
