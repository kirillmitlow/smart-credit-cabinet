# T-390. Выдать метрики Prometheus из таблиц Postgres и Redis

| | |
|---|---|
| Статус | TODO |
| Владелец | не назначен (Claude Code или Codex, по очереди смен) |
| Ветка | `feat/metrics-prometheus` |
| Оценка | ~5 ч |
| Приоритет | S (Should) |
| Тонкий сквозной сценарий | нет |
| Зависит от | [T-231](T-231-circuit-breaker.md), [T-250](T-250-applications-model-api.md), [T-278](T-278-outbox-relay.md), [T-352](T-352-sse-event-stream.md) |

## Цель

`GET /metrics` (только внутри сети) показывает заявки по статусам, решения по исходам, длительность шагов, вызовы систем, состояние предохранителей, очередь outbox, соединения SSE, HTTP.

## Входит / не входит

- **Входит:** подсчёт из таблиц с кэшем 5 с, предохранители из Redis, HTTP и SSE — из `api`; метрики из [50-10](../../50-architecture/10-audit-and-observability.md): `applications_by_status`, `decisions_total`, `pipeline_step_duration_seconds`, `integration_calls_total`, `circuit_breaker_state`, `outbox_pending`, `outbox_dead_total`, `celery_queue_length`, `sse_connections`; мини-панель в продукте читает те же данные через `/health/deps`.
- **Не входит:** Prometheus/Grafana (профиль `obs`, после основного).

## Входные документы

- [50-10](../../50-architecture/10-audit-and-observability.md): Аудит и наблюдаемость
- [50-15](../../50-architecture/15-reliability-and-scaling.md): Надёжность и масштабирование
- [60-05](../../60-frontend/05-demo-panel.md): Демо-панель

## Критерии приёмки

- [ ] `/metrics` не проходит через публичный прокси
- [ ] Метрики не содержат персональных данных
- [ ] Частый опрос не нагружает Postgres (кэш 5 с)
- [ ] Тесты написаны и зелёные (`make check`)
- [ ] Документация и OpenAPI обновлены, если менялся контракт
- [ ] Запись в журнале

## Тесты

integration: значения после прогона персоны.

## Заметки для реализации

- Если упрёмся в процессы Celery — запасной путь `prometheus_client multiprocess` ([50-10](../../50-architecture/10-audit-and-observability.md)).
