# T-502. Собрать основной docker-compose.yml со всеми сервисами и проверками готовности

| | |
|---|---|
| Статус | TODO |
| Владелец | Агент A/B (любой сменщик) |
| Ветка | `chore/compose-main` |
| Оценка | ~5 ч |
| Зависит от | [T-500](T-500-monorepo-skeleton.md), [T-503](T-503-db-init.md), [T-100](T-100-mocks-skeleton.md), [50-01](../../50-architecture/01-overview.md), [50-14](../../50-architecture/14-deployment.md) |
| Приоритет | M (Must) |
| Веха | V1 ([график](../02-schedule.md)) |

## Цель

Одна команда поднимает весь стенд в правильном порядке. На первом шаге у `api`, `worker`, `beat` и `web` могут быть заглушки, главное — порядок, healthcheck и лимиты памяти уже настоящие.

## Входит / не входит

- **Входит:**
  - Сервисы: `postgres` (17), `redis` (AOF включён ради сессий), `db-init`, пять моков, `api`, `worker`, `beat`, `web`; для ещё не готовых — образ-заглушка с `/health/ready`
  - `depends_on` только с `service_healthy`/`service_completed_successfully`; порядок из 50-14 (Postgres → `db-init` → моки → `mock-scenarios` → `api` → `worker`/`beat`/`web`)
  - Healthcheck каждого сервиса, `mem_limit` по таблице 50-01, перезапуск, `x-`-якоря (`x-mock`, `x-api-env`)
  - Тома Postgres и Redis; `docker compose down` не трогает тома
  - Подстановки `${VAR:-значение}` совпадают с `.env.example` ([T-505](T-505-env-example.md))
- **Не входит:**
  - Порты на хосте и `override` ([T-504](T-504-compose-override-ports.md))
  - Профили `ai`, `obs`, облачный ([T-506](T-506-compose-ai-profile.md), [T-508](T-508-compose-obs-profile.md), [T-507](T-507-compose-cloud.md))
  - Dockerfile `api` и `web` (задачи `api` и фронта)

## Входные документы

- [50-01](../../50-architecture/01-overview.md) (схема, порядок запуска, память)
- [50-14](../../50-architecture/14-deployment.md)
- [50-13](../../50-architecture/13-config-and-profiles.md)
- [Спецификация моков](../../../specs/mocks.md), раздел 3.1

## Критерии приёмки

- [ ] `docker compose up --wait` на чистой машине доходит до «все healthy» без ручных действий
- [ ] Порядок запуска соответствует таблице 50-14; `api` ждёт `mock-scenarios` в состоянии `healthy`
- [ ] `docker compose config` не выдаёт предупреждений; значения по умолчанию совпадают с `.env.example`
- [ ] Сумма `mem_limit` основного профиля соответствует расчёту 50-01 (≈ 2,3 ГБ)
- [ ] Остановка и повторный запуск сохраняют данные; `down -v` сбрасывает всё
- [ ] Тесты написаны и зелёные
- [ ] Документация и OpenAPI обновлены, если менялся контракт
- [ ] Запись в журнале
- [ ] Выполнено [определение готовности](../04-definition-of-done.md) (линтеры, PR по шаблону, статус задачи обновлён)

## Тесты

Проверка скриптом [T-515](T-515-smoke-script.md) (`smoke.sh`) и вручную на чистой машине; в CI — задание `e2e` ([T-512](T-512-ci-e2e.md)).

## Заметки для реализации

- Миграции применяет только `api`; `worker` и `beat` ждут его готовности (иначе гонка).
- Первая сборка 5–10 минут; готовность после `up` 60–90 секунд — цифры плановые, замерить ([T-534](T-534-resource-measurement.md)).
- По D-094 профиль `ai` включён везде, а 50-13/50-14 пока описывают его как профиль; детали — [T-506](T-506-compose-ai-profile.md).
