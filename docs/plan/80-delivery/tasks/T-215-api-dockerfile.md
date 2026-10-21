# T-215. Собрать Dockerfile образа `api`/`worker`/`beat` и точку входа

| | |
|---|---|
| Статус | DONE |
| Владелец | не назначен (Claude Code или Codex, по очереди смен) |
| Ветка | `feat/api-dockerfile` |
| Оценка | ~4 ч |
| Приоритет | M (Must) |
| Тонкий сквозной сценарий | да |
| Зависит от | [T-200](T-200-api-skeleton.md), [T-201](T-201-db-and-migrations.md), [T-205](T-205-celery-skeleton.md), [T-500](T-500-monorepo-skeleton.md) |

## Цель

Один образ `scc-api` для трёх сервисов: compose ([T-502](T-502-compose-main.md)) запускает его разными командами. Сборка воспроизводима по lock-файлу, процесс не root.

## Входит / не входит

- **Входит:** многоступенчатый Dockerfile: `uv sync --frozen` (падает при расхождении lock), финальный слой без компиляторов, непривилегированный пользователь, `python:3.13-slim-bookworm` по точному тегу; команды запуска `uvicorn`, `celery worker -Q pipeline,outbox,default`, `celery beat`; миграции при старте `api` под advisory lock ([T-201](T-201-db-and-migrations.md)); хелсчеки ([T-209](T-209-health-endpoints.md), файл воркера); системные библиотеки WeasyPrint (Pango/Cairo) и открытые шрифты — слот под [T-336](T-336-pdf-generation-weasyprint.md); `docs/` в образ не копируется (D-081); метка версии и `engine_version` (хеш коммита) как build-arg.
- **Не входит:** сам compose, порты, профили ([T-502](T-502-compose-main.md), [T-504](T-504-compose-override-ports.md)); публикация образа в GHCR (только в момент сдачи, D-083, [T-514](T-514-ci-release-ghcr.md)).

## Входные документы

- [50-14](../../50-architecture/14-deployment.md): Развёртывание
- [50-02](../../50-architecture/02-tech-stack.md): Технологический стек
- [50-01](../../50-architecture/01-overview.md): Архитектура: контейнеры и потоки данных
- [50-09](../../50-architecture/09-security.md): Безопасность

## Критерии приёмки

- [ ] `docker build` на чистой машине собирает образ без доступа к PyPI вне lock-файла
- [ ] Образ стартует как `api`, `worker`, `beat` одной командой смены `CMD`, процесс не root
- [ ] В образе нет `docs/`, `.env`, тестов и dev-зависимостей (scikit-learn, pandas и др.)
- [ ] `engine_version` доступен приложению из сборки, а не из часов
- [ ] Тесты написаны и зелёные (`make check`)
- [ ] Документация и OpenAPI обновлены, если менялся контракт
- [ ] Запись в журнале

## Тесты

smoke: `docker run` образа с `GET /health/live`; сборка в CI ([T-509](T-509-ci-skeleton.md)).

## Заметки для реализации

- Размер образа растёт при добавлении WeasyPrint на 100–150 МБ ([50-12](../../50-architecture/12-files-and-documents.md)); слой с системными библиотеками выносить отдельно для кэша.
