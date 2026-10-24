# Чек-лист сдачи: каждый пункт кейса — файл — задача — статус

| | |
|---|---|
| Статус | APPROVED 21.10.2026 (план одобрен целиком, D-097) |
| Владелец | Агент A |
| Зависит от | [case.md, стр. 7](../../case.md), [матрица требований](../10-product/01-requirements-matrix.md), [80-02](02-schedule.md), [70-08](../70-quality/08-ci-pipeline.md) |
| Решения | Реализует D-001, D-064, D-081, D-083; закрывает «дыру» RQ-45 из матрицы требований |
| Обновлено | 21.10.2026 |

## Зачем

Жюри проверяет по чек-листу со стр. 7 кейса. Здесь каждому его пункту и каждому требованию `RQ-1x` сопоставлены **конкретный файл или путь в репозитории**, задача, которая его создаёт, и способ проверки. Пустая клетка «Где лежит» или «Задача» — дыра в плане. Финальную сверку делают дважды: перед заморозкой ([T-542](tasks/T-542-freeze-regression.md)) и перед тегом ([T-538](tasks/T-538-repo-prep-submission.md)).

Статусы: ⬜ не начато · 🟨 в работе · ✅ готово и проверено · ➖ осознанно не делаем (с причиной). Это живой список: статусы обновляются по доказательствам, а не проценту готовности. Документационный пакет 24.10 — [отчёт C](../reviews/C-2026-10-24-jury-package-refresh.md); расширенные задачи генерации/CI и финальная репетиция остаются открыты.

## Пункты чек-листа со стр. 7 кейса

| № | Пункт кейса | RQ | Где лежит | Задачи | Как проверяем | Статус |
|---|---|---|---|---|---|---|
| 1 | GitHub-репозиторий с историей коммитов, commit hash или тег на дедлайн | 10 | Репозиторий; тег `submission`; hash и дата в начале `README.md`; релиз с заметками | [T-538](tasks/T-538-repo-prep-submission.md), [T-539](tasks/T-539-release-and-tag.md) | История читаема (`[A]`/`[B]`), тег указывает на коммит с зелёным полным CI | ⬜ |
| 2 | Доступ для аккаунта `alfa-hack-2026` (репозиторий приватный) | 10 | Настройки репозитория GitHub (действие пользователя) | [T-538](tasks/T-538-repo-prep-submission.md) | Пользователь подтверждает доступ; в журнал запись | ⬜ |
| 3 | Docker-конфигурация, единый воспроизводимый запуск на обычном ПК | 11 | `docker-compose.yml`, `docker-compose.override.yml`, `docker-compose.cloud.yml`, `Dockerfile` в `api/`, `mocks/`, `web/`, `nlu/`, `deploy/db-init/` | [T-502](tasks/T-502-compose-main.md), [T-503](tasks/T-503-db-init.md), [T-504](tasks/T-504-compose-override-ports.md), [T-507](tasks/T-507-compose-cloud.md), [T-541](tasks/T-541-image-build-policy.md), [T-100](tasks/T-100-mocks-skeleton.md) + задачи Dockerfile `api`/`web` | Проверка на чистой машине: Linux ([T-535](tasks/T-535-clean-machine-linux.md)), Windows ([T-536](tasks/T-536-windows-check-pack.md)); `docker stats` ≤ 4 ГБ ([T-534](tasks/T-534-resource-measurement.md)) | ⬜ |
| 4 | Lock-файлы и зафиксированные версии | 13 | `api/uv.lock`, `mocks/uv.lock`, `nlu/models.lock`, lock-файл `pnpm` в `web/`, `.python-version`, `.nvmrc`, точные теги образов | [T-500](tasks/T-500-monorepo-skeleton.md), [T-100](tasks/T-100-mocks-skeleton.md), [T-509](tasks/T-509-ci-skeleton.md) + задачи зависимостей `api`/`web` | CI ставит строго по lock (`uv sync --frozen`, `pnpm --frozen-lockfile`); образы без `latest` | ⬜ |
| 5 | `README.md`: назначение, архитектура, требования, запуск, конфигурация и env, компоненты, пошаговая проверка | 14 | `README.md` в корне | [T-530](tasks/T-530-readme-static.md), [T-531](tasks/T-531-readme-generated.md), [T-532](tasks/T-532-jury-self-check-readme.md), [T-505](tasks/T-505-env-example.md) | Структура по [80-06](06-readme-plan.md); репетиция [T-533](tasks/T-533-jury-rehearsal.md) | 🟨 (23.10: README написан по проверенному стенду, [T-530](tasks/T-530-readme-static.md) и [T-532](tasks/T-532-jury-self-check-readme.md) PARTIAL) |
| 6 | Синтетические тестовые данные и тестовые учётные записи | 15, 52 | 9 персон и 10 технических сценариев в `mocks/app/roles/scenarios/builtin.py`; таблица ИНН в `README.md`; `GET /scenarios` и `GET /demo/personas` | [T-131](tasks/T-131-mocks-persona-sokolova.md)…[T-135](tasks/T-135-mocks-technical-scenarios.md), [T-141](tasks/T-141-mocks-persona-numbers-check.md), [T-531](tasks/T-531-readme-generated.md) | Оракул [30-17](../30-decisioning/17-persona-walkthrough.md); все ИНН региона `00` с верной контрольной суммой | ⬜ |
| 7 | `THIRD_PARTY_NOTICES` с компонентами, моделями, датасетами, сервисами и смоделированными интеграциями | 16 | [THIRD_PARTY_NOTICES](../../../THIRD_PARTY_NOTICES.md), [licenses](../../../licenses/README.md) | [T-524](tasks/T-524-third-party-notices.md) | Задание CI `notices`; ручной раздел проверен | 🟨 (реестр и тексты есть; генератор/CI и ОС-пакеты не закрыты) |
| 8 | Архитектурная схема | 17 | [architecture.md](../../architecture/architecture.md), Mermaid | [T-525](tasks/T-525-diagram-export-architecture.md) | Схема совпадает со списком сервисов compose | 🟨 (схема сверена; экспорт/CI отдельно) |
| 9 | Описание API и OpenAPI/Swagger | 18 | `docs/api/api.openapi.yaml`, пять `docs/api/mock-*.openapi.yaml`, `docs/api/README.md`; Swagger на `/docs` | [T-139](tasks/T-139-mocks-openapi-export.md), [T-543](tasks/T-543-make-openapi-all.md), [T-511](tasks/T-511-ci-contracts-security-notices.md) + OpenAPI `api` | Выгрузка из кода равна закоммиченным файлам; Spectral и `oasdiff` | ⬜ |
| 10 | Коллекция запросов | 19 | [Postman v2.1](../../api/postman_collection.json), существующий [Bruno](../../api/collection/) | [T-140](tasks/T-140-mocks-bruno-collection.md), [T-544](tasks/T-544-bruno-collection-api.md), [T-512](tasks/T-512-ci-e2e.md) | `bru run` зелёный в CI на чистом стенде | 🟨 (4 пути Newman зелёные; полный Bruno/CI отдельно) |
| 11 | Диаграмма состояний заявки | 20 | [state_machine.md](../../architecture/state_machine.md), Mermaid | [T-526](tasks/T-526-diagram-states.md) + стейт-машина `api` | Тест «диаграмма = таблица переходов» | 🟨 (29 переходов = код; экспорт/CI отдельно) |
| 12 | Модель данных | 21 | [data_model.md](../../architecture/data_model.md), Mermaid | [T-527](tasks/T-527-diagram-er.md) + модели `api` | Набор таблиц на диаграмме равен базе после миграций | 🟨 (26 таблиц / 42 FK = чистая БД; экспорт/CI отдельно) |
| 13 | Тестовые сценарии | 22 | [test-scenarios.md](../../test-scenarios.md), README, api/tests/personas, web/e2e | [T-528](tasks/T-528-test-scenarios-catalog.md), [T-523](tasks/T-523-check-docs-ts-labels.md), [T-517](tasks/T-517-personas-api-harness.md), [T-518](tasks/T-518-playwright-harness.md) | Сверка меток `check-docs`; хотя бы один человек прошёл ручные сценарии | 🟨 (4 основных пути; полный каталог технических ветвей отдельно) |
| 14 | *(желательно)* Публикация на внешнем сервере | 12 | Ссылка и дата проверки в `README.md` | [T-507](tasks/T-507-compose-cloud.md), [T-540](tasks/T-540-cloud-stand.md) (ждёт Q-008) | `smoke.sh` против стенда | ⬜ |

## Остальные требования с артефактами (`RQ-1x…2x`)

| RQ | Что требует | Где лежит | Задачи | Статус |
|---|---|---|---|---|
| RQ-10 | Тег, hash, доступ | Строки 1–2 таблицы выше | [T-538](tasks/T-538-repo-prep-submission.md), [T-539](tasks/T-539-release-and-tag.md) | ⬜ |
| RQ-11 | Docker, воспроизводимый запуск | Строка 3 | [T-502](tasks/T-502-compose-main.md), [T-535](tasks/T-535-clean-machine-linux.md) | ⬜ |
| RQ-12 | Облачная публикация (желательно) | Строка 14 | [T-540](tasks/T-540-cloud-stand.md) | ⬜ |
| RQ-13 | Lock-файлы | Строка 4 | [T-500](tasks/T-500-monorepo-skeleton.md), [T-509](tasks/T-509-ci-skeleton.md) | ⬜ |
| RQ-14 | README | Строка 5 | [T-530](tasks/T-530-readme-static.md)…[T-532](tasks/T-532-jury-self-check-readme.md) | ⬜ |
| RQ-15 | Тестовые данные и учётки для e2e | Строка 6; вход ИНН + код на экране (D-062), андеррайтер — кнопкой | [T-131](tasks/T-131-mocks-persona-sokolova.md)…[T-135](tasks/T-135-mocks-technical-scenarios.md), [T-518](tasks/T-518-playwright-harness.md) | ⬜ |
| RQ-16 | `THIRD_PARTY_NOTICES` | Строка 7 | [T-524](tasks/T-524-third-party-notices.md) | ⬜ |
| RQ-17 | Схема архитектуры | Строка 8 | [T-525](tasks/T-525-diagram-export-architecture.md) | ⬜ |
| RQ-18 | OpenAPI | Строка 9 | [T-139](tasks/T-139-mocks-openapi-export.md), [T-543](tasks/T-543-make-openapi-all.md) | ⬜ |
| RQ-19 | Коллекция запросов | Строка 10 (в матрице 10-01 указано 70-04, фактически прогон описан в [70-05](../70-quality/05-integration-and-e2e.md)) | [T-140](tasks/T-140-mocks-bruno-collection.md), [T-544](tasks/T-544-bruno-collection-api.md) | ⬜ |
| RQ-20 | Диаграмма состояний | Строка 11 | [T-526](tasks/T-526-diagram-states.md) | ⬜ |
| RQ-21 | Модель данных | Строка 12 | [T-527](tasks/T-527-diagram-er.md) | ⬜ |
| RQ-22 | Тестовые сценарии | Строка 13 | [T-528](tasks/T-528-test-scenarios-catalog.md) | ⬜ |
| RQ-23 | Работающий прототип, а не экраны | Весь стенд: `docker compose up`; раздел «Самопроверка» README | V3…V10 ([80-02](02-schedule.md)), [T-533](tasks/T-533-jury-rehearsal.md) | ⬜ |
| RQ-24 | Новостная лента | ➖ не делаем: организаторы подтвердили, что к кейсу не относится (D-019) | — | ➖ |

## Требования, влияющие на сдачу (выборочно)

| RQ | Что должно быть видно | Где лежит | Задачи | Статус |
|---|---|---|---|---|
| RQ-41 | Готовность к проверке: инструкция, данные, сброс | Раздел «Самопроверка» README, демо-панель `/demo`, [80-07](07-jury-self-check.md) | [T-532](tasks/T-532-jury-self-check-readme.md), [T-533](tasks/T-533-jury-rehearsal.md) | ⬜ |
| RQ-44 | Enterprise: надёжность, хаос, идемпотентность | Хаос-тесты H-01…H-14, нагрузка, раздел «Надёжность и масштабирование» README | [T-512](tasks/T-512-ci-e2e.md), [T-513](tasks/T-513-ci-nightly-full.md), [T-520](tasks/T-520-locust-harness.md) | ⬜ |
| RQ-45 | Потенциал развития, обоснование решений | `docs/adr/`, раздел «Развитие» README (закрывает «дыру» матрицы) | [T-529](tasks/T-529-adr-folder.md), [T-530](tasks/T-530-readme-static.md) | ⬜ |
| RQ-53 | Автономность, запуск без интернета | Проверка офлайн после сборки | [T-535](tasks/T-535-clean-machine-linux.md) | ⬜ |
| RQ-55 | Упрощения описаны явно | Раздел «Ограничения и допущения» README; «Смоделированные интеграции» в `THIRD_PARTY_NOTICES` | [T-530](tasks/T-530-readme-static.md), [T-524](tasks/T-524-third-party-notices.md) | ⬜ |
| RQ-67 | Проверка качества модели | Таблица «Качество» README, `synthetic-report`, оговорка про синтетику | [T-521](tasks/T-521-synthetic-report-ci.md), [T-531](tasks/T-531-readme-generated.md) | ⬜ |

## Условия выпуска (не из кейса, но обязательны)

| Условие | Основание | Задача | Статус |
|---|---|---|---|
| Образы в GHCR опубликованы **не раньше 26.10** и публичны; код в них виден всем | D-081, D-083 | [T-514](tasks/T-514-ci-release-ghcr.md), [T-539](tasks/T-539-release-and-tag.md) | ⬜ |
| В образах нет `docs/`, PDF кейса, `.env` | D-001, D-081 | [T-514](tasks/T-514-ci-release-ghcr.md), [T-538](tasks/T-538-repo-prep-submission.md) | ⬜ |
| Зелёный **полный** набор CI на коммите тега, включая `resilience` и `load` | [70-08](../70-quality/08-ci-pipeline.md) | [T-513](tasks/T-513-ci-nightly-full.md), [T-542](tasks/T-542-freeze-regression.md) | ⬜ |
| Первый запуск по README: сборка (до публикации) и скачивание (после) работают | D-081 | [T-541](tasks/T-541-image-build-policy.md) | ⬜ |
| README не обещает того, чего нет; список ограничений опубликован | RQ-55 | [T-542](tasks/T-542-freeze-regression.md) | ⬜ |

## Порядок финальной сверки

1. **Перед заморозкой (25.10, Ч1).** Агент проходит таблицы сверху вниз, открывая каждый файл, а не веря статусу. Пробел превращается в карточку или в строку «➖ не делаем» с причиной в README.
2. **Перед тегом (25.10 вечер и 26.10).** Вторая сверка на коммите кандидата; отдельно проверяются условия выпуска.
3. **Сверка лицом к жюри.** Человек не из разработки открывает репозиторий только с этим чек-листом и находит каждый артефакт за 5 минут ([T-533](tasks/T-533-jury-rehearsal.md)).

## Заметки для реализации

- Пути выбраны по [50-03](../50-architecture/03-repo-and-conventions.md); если задача меняет путь, правится эта таблица в том же PR.
- Если артефакт генерируется (OpenAPI, диаграммы, ER, таблицы README, `THIRD_PARTY_NOTICES`), в таблице указывается команда генерации и проверка «не отстаёт от источника» в CI.
