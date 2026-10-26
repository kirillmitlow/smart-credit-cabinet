# Сторонние компоненты и смоделированные интеграции

Метаданные компонентов проверены 24.10.2026 на main `1114d1c`; повторная сверка 25.10 с `8ff58fc` подтвердила, что все три lock-файла не изменились. Это перечень компонентов прототипа, не лицензия на собственный код проекта. Отдельная лицензия репозитория пока не выбрана.

## Как получены сведения

Точные версии взяты из [api/uv.lock](api/uv.lock), [mocks/uv.lock](mocks/uv.lock), [web/pnpm-lock.yaml](web/pnpm-lock.yaml) и Dockerfile. Лицензии Python проверены в `METADATA` установленных wheel **той же версии**, npm — в `package.json` той же версии. Для отсутствующих на macOS платформенных пакетов проверены официальные PyPI/npm metadata по точной версии. Источник каждой строки указан в [полном перечне](licenses/README.md) и [машинном реестре](licenses/inventory.json).

В реестре 655 уникальных пар пакет/версия: все сторонние пакеты обоих Python lock-файлов и обоих YAML-документов pnpm lock, включая тестовые, инструменты сборки и необязательные платформенные варианты. Значения лицензий сохранены как объявлены авторами: например, `BSD`, `Dual License` или `SEE LICENSE IN ...` не превращены автоматически в более точное SPDX-обозначение. Полные тексты, найденные в дистрибутивах (нормализованы переводы строк и завершающие пробелы), собраны в [licenses/](licenses/README.md), индексируются по SHA-256. Отсутствие локального текста отмечено пустым `licenseTexts`; ссылка на metadata остаётся источником сведений.

Неизвестное: полный состав системных пакетов Debian/Alpine и встроенных библиотек каждого Docker-образа здесь не инвентаризирован; теги PostgreSQL и Valkey не закрепляют patch/digest. Для образов ниже указана лицензия основного проекта, **не единая лицензия всего образа**. Детальные тексты системных пакетов сохраняются в самих образах (`/usr/share/doc`, сведения пакетного менеджера). Реестр не проверяет будущие изменения lock-файлов автоматически: скрипты и CI находятся в зоне Codex №1 (оставшаяся часть T-524).

## Основные зависимости приложения

| Компонент | Версия в lock | Применение | Лицензия по metadata |
|---|---|---|---|
| FastAPI | 0.157.0 | API и пять моков | MIT |
| Starlette | 1.9.0 | HTTP-основа FastAPI | BSD-3-Clause |
| Uvicorn | 0.54.0 | ASGI-сервер | BSD-3-Clause |
| Pydantic / pydantic-settings | 2.14.1 / 2.16.1 | Контракты и настройки | MIT |
| SQLAlchemy / Alembic | 2.1.5 / 1.20.0 | БД и миграции | MIT |
| psycopg / psycopg-binary | 3.3.6 | PostgreSQL из API | LGPL-3.0-only |
| asyncpg | 0.32.0 | PostgreSQL из моков | Apache-2.0 |
| Celery | 5.6.3 | Фоновые задачи | BSD-3-Clause |
| redis (Python-клиент) | 8.1.0 | Доступ к Valkey | MIT |
| HTTPX | 0.28.1 | HTTP-адаптеры | BSD-3-Clause |
| PyYAML | 6.0.3 | Политика кредитования | MIT |
| structlog / tenacity | 26.1.0 / 9.2.1 | Логи / повторы | MIT OR Apache-2.0 / Apache-2.0 |
| React / react-dom | 19.3.1 | Интерфейс | MIT |
| Mantine core / hooks | 9.7.3 | Компоненты интерфейса | MIT |
| TanStack React Query | 5.104.5 | Серверные данные в браузере | MIT |
| React Router | 7.18.4 | Навигация | MIT |
| React Hook Form / resolvers | 7.90.0 / 6.0.0 | Формы | MIT |
| Zod | 4.6.7 | Проверка ввода | MIT |
| pypdf / python-multipart | 6.21.2 / 0.0.32 | Проверка PDF / потоковая загрузка | BSD-3-Clause / Apache-2.0 |
| WeasyPrint | 70.0 | Генерация PDF договора и графика | BSD (точное объявление и текст в inventory) |
| PT Sans Regular / Bold | 2.003W OFL | Встроенная кириллица в PDF | OFL-1.1, [хеши и уведомление](licenses/pdf-fonts.json) |
| Unbounded (`@fontsource-variable/unbounded`) | 5.3.0 | Локально поставляемый шрифт заголовков (D-113) | OFL-1.1 |
| Onest (`@fontsource-variable/onest`) | 5.3.1 | Локально поставляемый шрифт текста (D-113) | OFL-1.1 |

Таблица сокращённая; версии и первичные metadata-ссылки **всех** зависимостей, включая dev, — в [licenses/README.md](licenses/README.md). В частности, LGPL у psycopg не подменяется MIT: [лицензия автора](https://github.com/psycopg/psycopg/blob/master/LICENSE.txt); binary-вариант включает библиотеки, что отдельно описано в [документации установки](https://www.psycopg.org/psycopg3/docs/basic/install.html#binary-installation). Metadata и доступные тексты включены в комплект.

Новые PDF-зависимости, включая fonttools/Pillow/Pyphen и платформенные варианты Brotli, включены в полный реестр по metadata точных версий. Лицензии Pyphen сохранены как заявленный набор GPLv2+/LGPLv2+/MPL1.1, без вывода о единой лицензии всего проекта. [WeasyPrint](https://github.com/Kozea/WeasyPrint/blob/main/LICENSE) использует BSD; полный текст из установленного wheel включён.

Шрифт PT Sans поставляется из api/app/modules/documents/fonts; OFL1.1 содержит Reserved Font Names PT Sans и ParaType. Полное уведомление, версия и SHA-256 обоих TTF записаны в [pdf-fonts.json](licenses/pdf-fonts.json).

Шрифт Inter поставляется в web-пакете, его официальная лицензия — [SIL OFL 1.1](https://github.com/rsms/inter/blob/master/LICENSE.txt). Mantine подтверждает [MIT](https://github.com/mantinedev/mantine). Отдельных пакетов внешних иконок в прямых зависимостях web нет; используемые транзитивные компоненты перечислены в реестре. Платные API, SMS- и email-сервисы в основной путь не входят.

## Среда выполнения и сборки

| Компонент / образ | Закреплённая версия или тег | Использование | Лицензия основного проекта и источник |
|---|---|---|---|
| CPython `python:3.13.16-slim-bookworm` | 3.13.16 | API, worker, beat, моки | PSF и включённые лицензии: [Python](https://docs.python.org/3.13/license.html) |
| PostgreSQL `postgres:17-bookworm` | ветка 17; patch/digest не закреплён | Один сервер, шесть БД | [PostgreSQL License](https://www.postgresql.org/about/licence/) |
| Valkey `valkey/valkey:8.1-bookworm` | ветка 8.1; patch/digest не закреплён | Сервис с именем `redis`: очередь, кэш, сессии | [BSD-3-Clause, COPYING ветки 8.1](https://github.com/valkey-io/valkey/blob/8.1/COPYING) |
| nginx `nginxinc/nginx-unprivileged:1.30.6-alpine3.24` | 1.30.6 / Alpine 3.24 | Статика и прокси web | [nginx: BSD-2-Clause](https://nginx.org/LICENSE); [сборка unprivileged: Apache-2.0 и включённые уведомления](https://github.com/nginx/docker-nginx-unprivileged/blob/main/LICENSE) |
| Node `node:24.22.1-bookworm-slim` | 24.22.1 | Только сборка web; в финальном web-образе Node нет | [MIT и включённые уведомления](https://github.com/nodejs/node/blob/main/LICENSE) |
| uv `ghcr.io/astral-sh/uv:0.13.0` | 0.13.0 | Только сборка Python-образов | [MIT](https://github.com/astral-sh/uv/blob/main/LICENSE-MIT) OR [Apache-2.0](https://github.com/astral-sh/uv/blob/main/LICENSE-APACHE) |
| pnpm | 12.14.0 | Сборка web | MIT, [metadata точной версии](https://registry.npmjs.org/pnpm/12.14.0) |

`redis` — имя сервиса и Python-клиента; сервер в этом стенде **Valkey**, лицензии современных Redis Server к нему не приписываются. Docker Desktop и Postman — необязательные инструменты пользователя, не компоненты образов приложения; запуск возможен с Docker Engine/Compose, проверка запросов — также curl и Bruno.

### Системные библиотеки PDF

В проверенном API-образе Dockerfile устанавливает Pango и HarfBuzz для WeasyPrint. Это наблюдаемые версии сборки, не закреплённые apt-зависимости: libpango-1.0-0 и libpangoft2-1.0-0 — **1.50.12+ds-1**, libharfbuzz-subset0 — **6.0.0+dfsg-3**. Основная лицензия Pango — [LGPL-2.1-or-later](https://docs.gtk.org/Pango/), HarfBuzz — условия [COPYING](https://github.com/harfbuzz/harfbuzz/blob/main/COPYING), включая MIT-подобное разрешение и дополнительные уведомления. Точные copyright-файлы Debian из проверенного образа сохранены в [pdf-native-runtime.json](licenses/pdf-native-runtime.json). Это дополнение не подменяет полную инвентаризацию всех транзитивных ОС-пакетов.

## Пять локальных мок-сервисов

Все пять — код этого проекта, версия `scc-mocks 0.1.0`, один [Dockerfile](mocks/Dockerfile), роли разделяются переменной `MOCK_ROLE`. Это **не обращения к реальным внешним системам**. Их зависимости включены в Python-реестр выше.

| Compose-сервис | Что моделируется | Предел модели |
|---|---|---|
| mock-registry | Реестр организаций/ИП, люди и роли, статус, банкротства ЕФРСБ | Синтетические записи и упрощённый JSON, без реестрового доступа |
| mock-tax | ФНС: налоги, отчётность; ЕИС: госконтракты | Синтетические срезы, не настоящие ФНС/ЕИС |
| mock-credit-bureau | БКИ: кредитная история, согласия, события заявок и договоров | Упрощённый локальный договор API, запросы условно «платные», денег не списывают |
| mock-bank-core | Счета бизнеса, месячные обороты, комплаенс, выдача, кредитные счета | Без настоящего открытия счёта, переводов и платежей |
| mock-scenarios | Подготовка, применение и сброс демо-компаний в четырёх моках; генерация синтетической выписки 1С | **Средство подготовки демонстрации**, не реальная внешняя банковская интеграция |

Спецификация и все упрощения: [docs/specs/mocks.md](docs/specs/mocks.md), раздел 12. ФССП, арбитраж, реестр залогов и МЧД не подключены и не изображаются готовыми интеграциями.

## Модели, данные и исследование

В Compose проверяемой версии нет LLM/NLU-сервиса и поставляемых весов моделей. Решение считает детерминированное ядро по [версии политики](api/policy/v1.yaml). Исследовательские материалы о моделях в истории и открытом PR #3 не означают включение моделей в поставку; лицензии гипотетических будущих весов здесь не объявляются проверенными.

Все демонстрационные компании, сотрудники, ИНН, финансовые ряды и кредитные истории **синтетические**, генерируются собственным кодом в [mocks/app/roles/scenarios](mocks/app/roles/scenarios). Покупных клиентских баз и загруженного внешнего обучающего датасета в данном стенде нет. Банковские источники и допущения в [реестре экономики](docs/plan/30-decisioning/18-economic-assumptions.md) служат обоснованием правил; это не обучающие данные и не настоящие банковские тарифы. Новостная лента исключена D-019.

Инструменты ИИ использовались при разработке; их подписки и учётные записи не требуются для запуска или проверки прототипа. Окончательная проверка новых зависимостей, системных пакетов образов и сведений о лицензии собственного кода остаётся частью подготовки релиза.
