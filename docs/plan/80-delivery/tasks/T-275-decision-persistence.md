# T-275. Сохранить решение: снимок, причины, переход статуса, оферта

| | |
|---|---|
| Статус | TODO |
| Владелец | не назначен (Claude Code или Codex, по очереди смен) |
| Ветка | `feat/decision-persistence` |
| Оценка | ~6 ч |
| Приоритет | M (Must) |
| Тонкий сквозной сценарий | да |
| Зависит от | [T-270](T-270-pipeline-skeleton.md), [T-272](T-272-pipeline-collect-sources.md), [T-273](T-273-pipeline-bureau-step.md), [T-274](T-274-policy-loader-versions.md), [T-300](T-300-decide-assembly.md), [T-251](T-251-application-state-machine.md), [T-252](T-252-events-and-audit.md) |

## Цель

Результат `decide()` фиксируется как неизменяемый снимок (D-030) и в той же транзакции меняет статус заявки; для `APPROVED` и `COUNTER_OFFER` создаётся основа предложения.

## Входит / не входит

- **Входит:** таблицы `decisions` (столбцы итога + JSONB `inputs`, `features`, `explain`, `snapshot_ids`) и `decision_reasons`; `inputs_hash`, `policy_version_id`, `engine_version` (хеш коммита из сборки); решение создаётся и для `NEEDS_INFO`, `MANUAL_REVIEW`; тексты причин сохраняются в снимке (Q-113); одна транзакция: решение + переход статуса + события + ключ уведомлений + outbox; идемпотентность по `run_key`; вызов заготовок: создание задач (`REVENUE_UNKNOWN`) и предложения ([T-340](T-340-offers-variants-accept.md)) через публичные интерфейсы модулей.
- **Не входит:** воспроизведение ([T-276](T-276-decision-replay-golden.md)); решение андеррайтера ([T-362](T-362-backoffice-decision.md)).

## Входные документы

- [30-01](../../30-decisioning/01-pipeline-overview.md): Конвейер решения: шаги, режимы, функция decide()
- [30-13](../../30-decisioning/13-policy-config-and-versioning.md): Конфиг правил, версии и воспроизведение решения
- [50-06](../../50-architecture/06-data-model.md): Модель данных базы `api`
- [50-05](../../50-architecture/05-async-processing.md): Фоновая обработка: Celery и Redis
- [20-02](../../20-process/02-application-states.md): Статусы заявки и переходы

## Критерии приёмки

- [ ] Запись нельзя изменить (триггер); решение андеррайтера — новая запись `source=UNDERWRITER`
- [ ] Повторный запуск не создаёт второго решения
- [ ] Для `sokolova` итог `APPROVED`, статус заявки `APPROVED`, события в журнале в правильном порядке
- [ ] `decide()` на `decisions.inputs` даёт тот же результат (зачаток INV-52)
- [ ] Тесты написаны и зелёные (`make check`)
- [ ] Документация и OpenAPI обновлены, если менялся контракт
- [ ] Запись в журнале

## Тесты

integration: полный прогон sokolova/romashka по заглушкам; unit: сборка записи.

## Заметки для реализации

- `engine_version` берётся из сборки образа, не из часов ([30-13](../../30-decisioning/13-policy-config-and-versioning.md)).
