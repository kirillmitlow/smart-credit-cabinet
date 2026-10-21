# T-200. Создать каркас `api`: FastAPI, настройки, границы модулей

| | |
|---|---|
| Статус | TODO |
| Владелец | не назначен (Claude Code или Codex, по очереди смен) |
| Ветка | `feat/api-skeleton` |
| Оценка | ~5 ч |
| Приоритет | M (Must) |
| Тонкий сквозной сценарий | да |
| Зависит от | [T-500](T-500-monorepo-skeleton.md), [T-501](T-501-linters-precommit.md) |

## Цель

Появляется пустое, но рабочее приложение `api`: запускается, отвечает на `/health/live`, настройки читаются из переменных окружения, границы модулей проверяются автоматически. Все остальные задачи бэкенда ложатся в готовые рельсы ([50-03](../../50-architecture/03-repo-and-conventions.md), раздел «Заметки для реализации»).

## Входит / не входит

- **Входит:** `api/pyproject.toml` и `uv.lock` (Python 3.13, версия закреплена в `.python-version`), структура `app/modules/<имя>/` для всех модулей из [50-04](../../50-architecture/04-modules-and-boundaries.md) с публичным `__init__.py`; `app/main.py` (FastAPI), `app/shared/settings.py` на pydantic-settings со всеми переменными из [50-13](../../50-architecture/13-config-and-profiles.md) (`APP_ENV`, `DEMO_MODE`, `POLICY_FILE`, `INTEGRATION_TIMEOUT_SCALE`…) и запретом секретов по умолчанию при `APP_ENV=cloud`; поверх общих линтеров из [T-501](T-501-linters-precommit.md): список строгих для mypy модулей (`decisioning`, `simulator`, `pipeline`, `applications`), набор `DTZ` в ruff для `api`, контракты import-linter R1–R4, R9 (их настройка отдана задачам `api`); цели `make check` и `make test` для `api`.
- **Не входит:** миграции и подключение к БД ([T-201](T-201-db-and-migrations.md)); Celery ([T-205](T-205-celery-skeleton.md)); бизнес-ручки.

## Входные документы

- [50-03](../../50-architecture/03-repo-and-conventions.md): Структура репозитория и соглашения
- [50-04](../../50-architecture/04-modules-and-boundaries.md): Модули `api` и правила зависимостей
- [50-02](../../50-architecture/02-tech-stack.md): Технологический стек
- [50-13](../../50-architecture/13-config-and-profiles.md): Настройки и профили запуска
- [70-01](../../70-quality/01-test-strategy.md): Стратегия тестирования

## Критерии приёмки

- [ ] `uvicorn app.main:app` стартует, `GET /health/live` отвечает 200
- [ ] `make check` проходит на пустом каркасе: ruff, mypy, import-linter
- [ ] Нарушение правила R1 (импорт `repo` чужого модуля) и R2 (импорт `sqlalchemy` в `decisioning`) ломает import-linter: проверено временным нарушающим коммитом, результат записан в описании PR
- [ ] При `APP_ENV=cloud` и значении секрета по умолчанию приложение не стартует (тест)
- [ ] Тест «чистоты» ядра из [50-04](../../50-architecture/04-modules-and-boundaries.md) заложен: пустая `decide()`-заглушка вызывается при закрытых сокетах
- [ ] Тесты написаны и зелёные (`make check`)
- [ ] Документация и OpenAPI обновлены, если менялся контракт
- [ ] Запись в журнале

## Тесты

unit: загрузка настроек (по умолчанию, из окружения, облачный режим без секретов); контрактный тест import-linter в `make check`.

## Заметки для реализации

- Первым коммитом кода идёт именно каркас: пустые модули с докстрингом-ссылкой на документ ([50-03](../../50-architecture/03-repo-and-conventions.md)).
- Если какая-то нужная библиотека не ставится на Python 3.13, откатиться на 3.12 одной строкой в `.python-version` и Dockerfile ([50-02](../../50-architecture/02-tech-stack.md), Q-046).
- Не добавлять зависимости «на будущее»: каждая приходит в своей задаче.
