# Моки внешних систем: спецификация

> Статус: черновик для согласования командой · 20.10.2026 (ред. 2: все данные в БД, сервис сценариев)
>
> Документ фиксирует, **что принимает и что возвращает каждый мок**, что он хранит, как ведёт себя при сбоях и как в него попадают тестовые данные. Это ТЗ для агента, который делает моки. Решения из прошлых обсуждений (4 мока, персоны, стоп-факторы, ядро) здесь не пересматриваются, только детализируются.

## Оглавление

0. [Задача для агента и её границы](#0-задача-для-агента-и-её-границы)
1. [Коротко](#1-коротко)
2. [Общие правила для всех моков](#2-общие-правила-для-всех-моков)
3. [Архитектура и хранение](#3-архитектура-и-хранение)
4. [mock-registry — ЕГРЮЛ / ЕГРИП](#4-mock-registry--егрюл--егрип)
5. [mock-tax — открытые сервисы ФНС](#5-mock-tax--открытые-сервисы-фнс)
6. [mock-credit-bureau — БКИ](#6-mock-credit-bureau--бки)
7. [mock-bank-core — АБС и комплаенс](#7-mock-bank-core--абс-и-комплаенс)
8. [Служебные эндпоинты: health, chaos, админ-API данных](#8-служебные-эндпоинты-health-chaos-админ-api-данных)
9. [Как `api` работает с моками](#9-как-api-работает-с-моками)
10. [Тестовые данные: сервис сценариев `mock-scenarios`](#10-тестовые-данные-сервис-сценариев-mock-scenarios)
11. [Тесты и артефакты сдачи](#11-тесты-и-артефакты-сдачи)
12. [Что упрощено по сравнению с реальностью](#12-что-упрощено-по-сравнению-с-реальностью)
13. [Открытые вопросы](#13-открытые-вопросы)

---

## 0. Задача для агента и её границы

**Сделать:**
- 4 мока внешних систем (разделы 4–7): бизнес-API, хранение в Postgres, chaos, health;
- у каждого мока **админ-API данных** (раздел 8.3), через который тестовые данные создаются, правятся и удаляются;
- сервис сценариев `mock-scenarios` (раздел 10): хранит описания тестовых компаний, сам заполняет моки при старте, умеет создать новую компанию одним запросом;
- встроенные сценарии — 9 персон и 5 технических (раздел 10.5);
- тесты, OpenAPI-файлы, коллекцию запросов (раздел 11).

**Не делать:**
- никакого интерфейса, в том числе админки и демо-панели. Ручная правка данных идёт через Swagger UI (`/docs`) и коллекцию запросов. Интерфейс потом сделает команда поверх этого же API;
- ничего в `api`: адаптеры, конвейер, скоринг, учётки кабинета. Раздел 9 описывает, как `api` будет вызывать моки, чтобы контракт под это подходил;
- никаких файлов с данными, которые читаются при работе (YAML, JSON, CSV). **Всё состояние в БД.** Встроенные сценарии — это код в образе, при первом старте он записывается в БД, и дальше источник правды только БД.

**Готово, когда:** `docker compose up` на пустом томе Postgres поднимает 5 сервисов. Через минуту все моки отвечают по всем персонам, а `POST /api/v1/scenarios` создаёт новую компанию, которую сразу видят все 4 мока.

---

## 1. Коротко

| Мок | Реальный аналог | Эндпоинты (`/api/v1/...`) | Состояние | Хранилище |
|---|---|---|---|---|
| `mock-registry` | ЕГРЮЛ / ЕГРИП (ФНС, через СМЭВ или агрегаторы типа DaData) | `GET companies/{inn}`, `GET persons/{inn}/roles` | Для `api` только чтение | Postgres, БД `mock_registry` |
| `mock-tax` | «Прозрачный бизнес», ГИР БО, реестр МСП, статус НПД, сервис блокировок счетов | `GET tax-profile/{inn}`, `GET financials/{inn}`, `GET sme-status/{inn}`, `POST self-employed/status`, `GET account-blocks/{inn}` | Для `api` только чтение | Postgres, БД `mock_tax` |
| `mock-credit-bureau` | НБКИ / ОКБ / Эквифакс | `POST credit-reports`, `GET credit-reports/{id}`, `POST submissions` | **Пишет**: запросы, отчёты, сведения от банка | Postgres, БД `mock_bki` |
| `mock-bank-core` | АБС банка + перечень Росфинмониторинга + платформа ЦБ «Знай своего клиента» | `GET customers/{inn}`, `GET customers/{inn}/turnover`, `POST customers/{inn}/accounts`, `POST disbursements`, `GET accounts/{n}`, `POST compliance/screening` | **Пишет**: счета, проводки, кредиты | Postgres, БД `mock_bank_core` |
| `mock-scenarios` | Не внешняя система, а **тестовая инфраструктура**: «пульт» для наполнения моков | `GET/POST/PATCH/DELETE scenarios`, `POST scenarios/{code}/apply`, `POST scenarios/reset`, `GET presets` | Хранит описания тестовых компаний | Postgres, БД `mock_scenarios` |

Главные решения:

1. **Мок отдаёт факты, выводы делает ядро.** Мок не считает DSCR, грейд или «тренд оборотов». Исключение — сводка в отчёте БКИ: она есть и в настоящих отчётах.
2. **Поведение как у настоящих систем**: свой API-ключ, задержка, независимые сбои, согласие для БКИ, идемпотентность у операций с деньгами.
3. **Петля замыкается.** Банк сообщает в БКИ о заявке и выданном кредите (`POST submissions`), а АБС реально зачисляет деньги (`POST disbursements`). Следующий отчёт БКИ по этому клиенту уже показывает наш кредит. Это видно на демо.
4. **Одна кодовая база, 5 контейнеров** (`MOCK_ROLE=registry|tax|bki|bank_core|scenarios`).
5. **Любой тестовый случай создаётся одним запросом.** Жюри хочет проверить «ООО, 2 года, выручка 5 млн/мес, просрочка 40 дней»: один `POST /api/v1/scenarios` с этими параметрами. Сервис сам генерирует ИНН, ОГРН, счёт, историю платежей и раскладывает данные по четырём мокам так, чтобы они не противоречили друг другу.

---

## 2. Общие правила для всех моков

### 2.1. Транспорт и формат

| Что | Правило |
|---|---|
| Протокол | REST + JSON, UTF-8. В жизни госданные идут через СМЭВ (XML/SOAP) или агрегаторов. Мы упрощаем транспорт, состав данных сохраняем |
| Базовый путь | `/api/v1` |
| Имена полей | `camelCase` (в Pydantic через `alias_generator=to_camel`) |
| Даты | ISO 8601: `2026-10-20` для дат, `2026-10-20T09:12:00Z` для моментов (всегда UTC) |
| Деньги | Целые рубли, `int`, суффикс `Rub`: `taxDebtRub`. Копейки не нужны ни одному из сценариев |
| Ставки, доли | `float` в процентах: `ratePercent: 21.5`, `sharePercent: 100` |
| Перечисления | `UPPER_SNAKE_CASE` строками |
| Отсутствие значения | `null`, поле не пропускаем. Тогда схема OpenAPI стабильна |

### 2.2. Обёртка ответа

Каждый успешный ответ (кроме НПД, см. 5.4) содержит блок `meta`:

```json
"meta": {
  "source": "EGRUL",
  "simulated": true,
  "requestId": "req_01JAK9Z3F0Q8",
  "retrievedAt": "2026-10-20T09:12:03Z",
  "dataActualAt": "2026-10-19"
}
```

- `source` — какая «система» ответила: `EGRUL`, `EGRIP`, `FNS_TRANSPARENT_BUSINESS`, `FNS_GIR_BO`, `FNS_RMSP`, `FNS_BLOCKS`, `CREDIT_BUREAU`, `BANK_CORE`, `COMPLIANCE`;
- `simulated: true` — всегда, чтобы данные никто не принял за реальные;
- `dataActualAt` — «сведения актуальны на» (у реестров это реальное понятие). Андеррайтер видит, насколько свежий факт.

### 2.3. Заголовки

| Заголовок | Направление | Зачем |
|---|---|---|
| `X-Api-Key` | запрос | Аутентификация потребителя. Без ключа `401`, ключ чужой роли `403` |
| `X-Request-Id` | запрос и ответ | Сквозной ID. Принимаем, если нет — генерируем; пишем в лог и в `meta` |
| `Idempotency-Key` | запрос | **Обязателен** для `POST disbursements`, `POST submissions`, `POST customers/{inn}/accounts`. Повтор с тем же ключом и тем же телом возвращает сохранённый ответ; с другим телом — `409 IDEMPOTENCY_KEY_REUSED` |
| `X-Mock-Scenario` | запрос | Только для тестов: `error`, `slow`, `timeout` ломают конкретный запрос |
| `Retry-After` | ответ | При `429` и `503` |

Ключи задаются через env: `MOCK_API_KEYS="api:<key>"` и отдельный `MOCK_ADMIN_KEY` для `/admin/*`. В реальности здесь mTLS и сертификаты СМЭВ/БКИ; упрощение описано в разделе 12.

### 2.4. Ошибки: RFC 7807

Все ошибки возвращаются как `application/problem+json` с машинным полем `code`:

```json
{
  "type": "https://mocks.smart-credit.local/problems/consent-expired",
  "title": "Consent expired",
  "status": 403,
  "code": "CONSENT_EXPIRED",
  "detail": "Срок действия согласия истёк 2026-04-01",
  "requestId": "req_01JAK9Z3F0Q8"
}
```

Общие коды для всех моков:

| HTTP | `code` | Когда |
|---|---|---|
| 400 | `INN_INVALID` | Длина не 10/12 или не сходится контрольная сумма |
| 400 | `VALIDATION_ERROR` | Тело не прошло схему (Pydantic). В `errors[]` — поля |
| 401 | `UNAUTHORIZED` | Нет или неверный `X-Api-Key` |
| 409 | `IDEMPOTENCY_KEY_REUSED` | Ключ уже использован с другим телом |
| 429 | `RATE_LIMITED` | Превышен лимит (включается в chaos, см. 8.2) |
| 503 | `SERVICE_UNAVAILABLE` | Chaos-режим `error`/`down` |

**Правило про 404.** `404` только для «карточечных» ресурсов, которых нет: компании нет в ЕГРЮЛ, отчётности нет в ГИР БО, клиента нет в АБС. Если ресурс — проверка признака, отсутствие — это ответ, а не ошибка: «не в реестре МСП» → `200 {"inRegistry": false}`, «нет кредитной истории» → `200 {"hasHistory": false}`, «нет блокировок» → `200 {"decisions": []}`.

### 2.5. Время и относительные даты

Персоны не должны «стареть»: «Быстрый старт» должен быть 3-месячным и в день защиты, и через полгода. Поэтому:

- все сервисы считают «сегодня» по `MOCK_TODAY` (по умолчанию — реальная дата);
- в **сценариях** даты пишутся относительно: `-3M`, `-9y`, `-14d`, `-2y3M`, или параметром вроде `ageMonths: 3`. В моки при применении сценария уходят уже абсолютные даты;
- обороты и история платежей в сценарии задаются «от старого к новому» и привязываются к последним полным месяцам на момент применения;
- если демо-стенд живёт долго, `POST /api/v1/scenarios/reset` применяет сценарии заново, и даты снова свежие.

### 2.6. Логи

Структурный JSON: `ts`, `level`, `service`, `requestId`, `method`, `path`, `status`, `durationMs`, `chaos`. ИНН маскируем (`0017****22`), ФИО и номера счетов в лог не пишем.

---

## 3. Архитектура и хранение

### 3.1. Контейнеры и база

Postgres — **один общий контейнер** проекта, в нём же лежит база `api`. Каждый мок получает в нём **свою базу и своего пользователя** (database-per-service): контейнер общий, данные разделены, как у разных организаций в жизни. Никто не ходит в чужую базу. `api` видит данные БКИ только через HTTP БКИ, сервис сценариев пишет в моки только через их админ-API.

```yaml
# docker-compose.yml (фрагмент)
x-mock: &mock
  build: ./mocks
  environment: &mock-env
    MOCK_API_KEYS: ${MOCK_API_KEYS}
    MOCK_ADMIN_KEY: ${MOCK_ADMIN_KEY}
    MOCK_TODAY: ${MOCK_TODAY:-}
  depends_on: { db-init: { condition: service_completed_successfully } }
  healthcheck:
    test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/ready')"]
    interval: 5s
    retries: 10

services:
  mock-registry:
    <<: *mock
    environment: { <<: *mock-env, MOCK_ROLE: registry, MOCK_LATENCY_MS: "200-600",
                   DATABASE_URL: "postgresql+asyncpg://mock_registry:${MOCK_DB_PASSWORD}@postgres/mock_registry" }
  mock-tax:
    <<: *mock
    environment: { <<: *mock-env, MOCK_ROLE: tax, MOCK_LATENCY_MS: "200-800",
                   DATABASE_URL: "postgresql+asyncpg://mock_tax:${MOCK_DB_PASSWORD}@postgres/mock_tax" }
  mock-credit-bureau:
    <<: *mock
    environment: { <<: *mock-env, MOCK_ROLE: bki, MOCK_LATENCY_MS: "800-2500",
                   DATABASE_URL: "postgresql+asyncpg://mock_bki:${MOCK_DB_PASSWORD}@postgres/mock_bki" }
  mock-bank-core:
    <<: *mock
    environment: { <<: *mock-env, MOCK_ROLE: bank_core, MOCK_LATENCY_MS: "50-200", BANK_BIK: "040000999",
                   DATABASE_URL: "postgresql+asyncpg://mock_bank_core:${MOCK_DB_PASSWORD}@postgres/mock_bank_core" }
  mock-scenarios:
    <<: *mock
    environment: { <<: *mock-env, MOCK_ROLE: scenarios, MOCK_LATENCY_MS: "0",
                   DATABASE_URL: "postgresql+asyncpg://mock_scenarios:${MOCK_DB_PASSWORD}@postgres/mock_scenarios",
                   REGISTRY_URL: http://mock-registry:8000, TAX_URL: http://mock-tax:8000,
                   BKI_URL: http://mock-credit-bureau:8000, BANK_CORE_URL: http://mock-bank-core:8000 }
    depends_on:
      db-init: { condition: service_completed_successfully }
      mock-registry: { condition: service_healthy }
      mock-tax: { condition: service_healthy }
      mock-credit-bureau: { condition: service_healthy }
      mock-bank-core: { condition: service_healthy }
```

Базы и пользователи создаёт one-shot контейнер `db-init`: при каждом `docker compose up` он выполняет идемпотентный SQL (создать базу и пользователя, если их нет) и завершается. Работает и на пустом томе, и на существующем, когда добавился новый мок.

### 3.2. Что в какой базе

| База | Что хранит |
|---|---|
| `mock_registry` | Компании, ИП, физлица, связи (директор, учредитель) |
| `mock_tax` | Налоговые профили, бухотчётность по годам, МСП, НПД, блокировки |
| `mock_bki` | Субъекты, обязательства, запросы, заявки, отчёты, сведения от банка |
| `mock_bank_core` | Клиенты, счета, обороты по месяцам, кредиты, проводки, комплаенс-списки |
| `mock_scenarios` | Описания тестовых компаний (сценарии) и журнал их применения |

Общие правила для всех баз моков:

- **Схема создаётся миграциями при старте** (Alembic, свой набор миграций на роль). Пересборка контейнера данные не трогает: они в томе Postgres.
- **У каждой записи есть `origin`:** `SCENARIO` — создана сервисом сценариев, `RUNTIME` — появилась в ходе работы (запрос в БКИ, выдача кредита, открытие счёта). Это позволяет вернуть компанию в исходное состояние, не трогая остальные.
- **У каждого субъекта есть `scenario_code`** — из какого сценария он создан. По нему сервис сценариев удаляет и пересоздаёт данные компании.
- Мок **не знает про сценарии как формат**: он принимает только свой кусок данных через админ-API (раздел 8.3) в своих терминах.

### 3.3. Структура кода

```
mocks/
├── pyproject.toml, uv.lock, Dockerfile, alembic.ini
├── app/
│   ├── main.py              # create_app(): подключает роутеры по MOCK_ROLE
│   ├── settings.py          # pydantic-settings: MOCK_ROLE, LATENCY, ключи, DATABASE_URL
│   ├── common/
│   │   ├── inn.py           # валидация и генерация ИНН/ОГРН/КПП, маскирование
│   │   ├── accounts.py      # генерация номеров счетов с контрольным ключом
│   │   ├── problems.py      # ProblemException + обработчики → problem+json
│   │   ├── middleware.py    # request-id, латентность, chaos, логи
│   │   ├── auth.py          # require_api_key, require_admin
│   │   ├── idempotency.py   # хранит ответ по Idempotency-Key
│   │   ├── reldate.py       # "-3M" → date
│   │   ├── db.py            # engine, session, миграции при старте
│   │   └── schemas.py       # Meta, Problem, базовая CamelModel
│   ├── roles/
│   │   ├── registry/   { router.py, admin.py, schemas.py, service.py, models.py, migrations/ }
│   │   ├── tax/        { … то же … }
│   │   ├── bki/        { … то же … }
│   │   ├── bank_core/  { … то же … }
│   │   └── scenarios/
│   │       ├── router.py, schemas.py, models.py, migrations/
│   │       ├── presets.py   # пресеты и значения по умолчанию
│   │       ├── builtin.py   # 9 персон + технические, как код (Pydantic-объекты)
│   │       ├── expand.py    # сценарий → полные данные (ИНН, даты, обороты, история платежей)
│   │       ├── split.py     # полные данные → 4 куска для 4 моков
│   │       └── apply.py     # отправка кусков в админ-API моков, откат при ошибке
│   └── health.py, chaos.py  # /health/*, /admin/chaos
└── tests/
```

Базовые модели (общие для всех ролей):

```python
from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

Source = Literal["EGRUL", "EGRIP", "FNS_TRANSPARENT_BUSINESS", "FNS_GIR_BO", "FNS_RMSP",
                 "FNS_BLOCKS", "CREDIT_BUREAU", "BANK_CORE", "COMPLIANCE"]

class Meta(CamelModel):
    source: Source
    simulated: Literal[True] = True
    request_id: str
    retrieved_at: datetime
    data_actual_at: date | None = None

class Problem(CamelModel):
    type: str
    title: str
    status: int
    code: str
    detail: str | None = None
    request_id: str | None = None
    errors: list[dict] | None = None
```

В роутерах ответы описываются через `response_model` и `responses={400: {"model": Problem}, ...}`, тогда в `/docs` видны все коды ошибок. OpenAPI каждой роли выгружается в `docs/api/mock-<role>.openapi.yaml` скриптом `mocks/scripts/export_openapi.py`.

---

## 4. mock-registry — ЕГРЮЛ / ЕГРИП

**Реальный аналог.** ФНС ведёт два реестра: ЕГРЮЛ (организации) и ЕГРИП (ИП). Банки получают выписку через СМЭВ (вид сведений «Выписка из ЕГРЮЛ/ЕГРИП») или через агрегаторы. Ближайший JSON-аналог нашего контракта — DaData `findById/party` (блоки `state`, `management`, `founders`, `okved`) и `findAffiliated` (связи человека с компаниями).

**Кто вызывает.** `api` при вводе ИНН (автозаполнение анкеты) и в конвейере (статус, возраст бизнеса, руководитель, сверка с анкетой).

### 4.1. `GET /api/v1/companies/{inn}`

Тип записи определяется по длине ИНН: 10 цифр → ЕГРЮЛ, 12 цифр → ЕГРИП.

| Ответ | Когда |
|---|---|
| `200` `LegalEntity` или `IndividualEntrepreneur` (поле-дискриминатор `type`) | Найдено |
| `400 INN_INVALID` | Неверная контрольная сумма |
| `404 ENTITY_NOT_FOUND` | Нет в реестре (например, самозанятый Орлов) |

**Организация** (`GET /api/v1/companies/0017654322`):

```json
{
  "meta": { "source": "EGRUL", "simulated": true, "requestId": "req_…", "retrievedAt": "2026-10-20T09:12:03Z", "dataActualAt": "2026-10-19" },
  "type": "LEGAL_ENTITY",
  "inn": "0017654322",
  "kpp": "001701001",
  "ogrn": "1170000004569",
  "registrationDate": "2017-03-14",
  "fullName": "ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ «СТАНКОПРОМ»",
  "shortName": "ООО «СтанкоПром»",
  "legalForm": { "okopf": "12300", "name": "Общество с ограниченной ответственностью" },
  "status": { "code": "ACTIVE", "name": "Действующее", "since": "2017-03-14" },
  "pendingExclusion": null,
  "address": {
    "regionCode": "66",
    "regionName": "Свердловская область",
    "full": "620000, Свердловская обл., г. Екатеринбург, ул. Заводская, д. 1",
    "unreliable": null
  },
  "authorizedCapitalRub": 500000,
  "director": {
    "fullName": "Кузнецов Игорь Петрович",
    "inn": "001310000115",
    "position": "Генеральный директор",
    "since": "2017-03-14",
    "unreliable": null
  },
  "founders": [
    { "type": "PERSON", "fullName": "Кузнецов Игорь Петрович", "inn": "001310000115",
      "sharePercent": 100, "shareNominalRub": 500000, "unreliable": null }
  ],
  "okvedMain": { "code": "25.62", "name": "Обработка металлических изделий механическая" },
  "okvedAdditional": [ { "code": "28.41", "name": "Производство металлообрабатывающего оборудования" } ],
  "taxAuthority": { "code": "0001", "name": "Межрайонная ИФНС России № 1 (синтетическая)" },
  "lastRecord": { "grn": "2236600123456", "date": "2023-06-01" }
}
```

**ИП** (`GET /api/v1/companies/001234567887`): нет КПП, руководителя, учредителей, уставного капитала и полного адреса (у ИП в открытом доступе только регион).

```json
{
  "meta": { "source": "EGRIP", "…": "…" },
  "type": "INDIVIDUAL_ENTREPRENEUR",
  "inn": "001234567887",
  "ogrnip": "323000000123450",
  "registrationDate": "2023-04-12",
  "person": { "lastName": "Соколова", "firstName": "Анна", "middleName": "Сергеевна", "fullName": "Соколова Анна Сергеевна" },
  "status": { "code": "ACTIVE", "name": "Действующий", "since": "2023-04-12" },
  "region": { "code": "16", "name": "Республика Татарстан" },
  "okvedMain": { "code": "56.10", "name": "Деятельность ресторанов и услуги по доставке продуктов питания" },
  "okvedAdditional": [],
  "taxAuthority": { "code": "0002", "name": "ИФНС России № 2 (синтетическая)" },
  "lastRecord": { "grn": "423160000123451", "date": "2023-04-12" }
}
```

**Перечисления:**

| Поле | Значения |
|---|---|
| `status.code` (ЮЛ) | `ACTIVE`, `LIQUIDATING`, `LIQUIDATED`, `BANKRUPT`, `REORGANIZING` (как в DaData) |
| `status.code` (ИП) | `ACTIVE`, `CEASED` (прекратил деятельность), `BANKRUPT` |
| `founders[].type` | `PERSON`, `LEGAL_ENTITY` |

**Отметка о недостоверности** — реальное поле ЕГРЮЛ: налоговая проверила адрес, директора или учредителя и не подтвердила. Формат одинаковый для адреса, директора и учредителя:

```json
"unreliable": { "since": "2026-08-01", "grn": "2266600987654", "reason": "Результаты проверки достоверности" }
```

**Предстоящее исключение** (`pendingExclusion`) — ФНС решила исключить компанию как недействующую:

```json
"pendingExclusion": { "decisionDate": "2026-09-10", "grn": "2266600111222", "objectionsDeadline": "2026-12-10" }
```

Оба поля в MVP-стоп-факторы не входят, но в контракте есть с первого дня: потом добавляется только правило в `policy.yaml`.

### 4.2. `GET /api/v1/persons/{inn}/roles`

Где этот человек ИП, руководитель или учредитель. Нужен для сценария «владелец ввёл личный ИНН» и чтобы понять, кто вправе подписывать (директор по ЕГРЮЛ).

```json
{
  "meta": { "source": "EGRUL", "…": "…" },
  "personInn": "001310000115",
  "roles": [
    { "role": "DIRECTOR", "entityInn": "0017654322", "entityName": "ООО «СтанкоПром»",
      "entityStatus": "ACTIVE", "since": "2017-03-14", "sharePercent": null },
    { "role": "FOUNDER", "entityInn": "0017654322", "entityName": "ООО «СтанкоПром»",
      "entityStatus": "ACTIVE", "since": "2017-03-14", "sharePercent": 100 }
  ]
}
```

- `role`: `INDIVIDUAL_ENTREPRENEUR`, `DIRECTOR`, `FOUNDER`.
- Принимает только 12-значный ИНН, иначе `400 INN_INVALID`.
- Ничего не нашли → `200` с `roles: []`, не `404`.

### 4.3. Хранение — БД `mock_registry`

```
entities
  inn PK, type (LEGAL_ENTITY|INDIVIDUAL_ENTREPRENEUR), ogrn UNIQUE, kpp,
  person_inn FK NULL,                 -- для ИП: ссылка на физлицо
  registration_date, full_name, short_name, okopf_code, okopf_name,
  status_code, status_since, pending_exclusion JSONB,
  region_code, region_name, address_full, address_unreliable JSONB,
  authorized_capital_rub, okved_main, okved_additional TEXT[],
  tax_authority_code, tax_authority_name, last_record_grn, last_record_date,
  data_actual_at, origin, scenario_code

persons
  inn PK, last_name, first_name, middle_name, birth_date, origin, scenario_code

entity_roles                          -- руководители и учредители
  id PK, entity_inn FK, role (DIRECTOR|FOUNDER),
  person_inn FK NULL, founder_entity_inn NULL,   -- учредитель-человек или учредитель-компания
  position, share_percent, share_nominal_rub, since, unreliable JSONB

okved                                 -- справочник кодов и названий, заполняется миграцией
  code PK, name
```

`GET /persons/{inn}/roles` собирается из `entity_roles` и `entities` (для ИП роль `INDIVIDUAL_ENTREPRENEUR`).

---

## 5. mock-tax — открытые сервисы ФНС

Внутри пять «сервисов», у каждого свой реальный аналог и свой `meta.source`.

### 5.1. `GET /api/v1/tax-profile/{inn}` — «Прозрачный бизнес»

**Реальный аналог:** pb.nalog.ru. Там есть спецрежимы, среднесписочная численность, уплаченные налоги, недоимка и задолженность по пеням и штрафам, налоговые правонарушения, доходы и расходы по отчётности, признаки массовости и дисквалификации.

```json
{
  "meta": { "source": "FNS_TRANSPARENT_BUSINESS", "dataActualAt": "2026-10-01", "…": "…" },
  "inn": "0015557771",
  "taxRegimes": [ { "code": "USN_INCOME_MINUS_EXPENSES", "year": 2025 } ],
  "avgHeadcount": { "value": 12, "year": 2025 },
  "taxesPaid": [ { "year": 2025, "totalRub": 3410000 }, { "year": 2024, "totalRub": 3120000 } ],
  "debts": { "asOf": "2026-10-01", "taxDebtRub": 1150000, "penaltiesRub": 42000, "finesRub": 0 },
  "incomeExpenses": { "year": 2025, "incomeRub": 95000000, "expensesRub": 91000000 },
  "taxOffenses": { "year": 2025, "count": 1, "finesRub": 5000 },
  "riskFlags": {
    "massAddress": false,
    "massDirector": false,
    "massFounder": false,
    "disqualifiedManagement": false,
    "noReportsOverYear": false
  }
}
```

- `taxRegimes[].code`: `OSNO`, `USN_INCOME`, `USN_INCOME_MINUS_EXPENSES`, `PSN`, `ESHN`, `AUSN`, `NPD`.
- `debts.taxDebtRub` — с 2023 года это отрицательное сальдо единого налогового счёта (ЕНС).
- `incomeExpenses` у ИП `null`: бухотчётности у них нет.
- `404 ENTITY_NOT_FOUND`, если такого налогоплательщика-бизнеса нет.

### 5.2. `GET /api/v1/financials/{inn}?year=2025` — ГИР БО (бухотчётность)

**Реальный аналог:** bo.nalog.ru, годовая отчётность организаций. Отдаём **реальные коды строк** баланса и отчёта о финансовых результатах, плюс именованную сводку, чтобы потребителю не нужно было помнить коды.

```json
{
  "meta": { "source": "FNS_GIR_BO", "…": "…" },
  "inn": "0017654322",
  "year": 2025,
  "availableYears": [2025, 2024, 2023],
  "formType": "FULL",
  "submittedAt": "2026-03-28",
  "lines": {
    "1100": { "current": 182000000, "previous": 171000000 },
    "1200": { "current": 141000000, "previous": 128000000 },
    "1300": { "current": 196000000, "previous": 165300000 },
    "1400": { "current": 22000000,  "previous": 31000000 },
    "1500": { "current": 105000000, "previous": 102700000 },
    "1600": { "current": 323000000, "previous": 299000000 },
    "2110": { "current": 420000000, "previous": 388000000 },
    "2200": { "current": 41500000,  "previous": 36900000 },
    "2330": { "current": 1900000,   "previous": 3100000 },
    "2400": { "current": 30700000,  "previous": 27400000 }
  },
  "summary": {
    "revenueRub": 420000000,
    "salesProfitRub": 41500000,
    "interestPayableRub": 1900000,
    "netProfitRub": 30700000,
    "totalAssetsRub": 323000000,
    "equityRub": 196000000,
    "longTermLiabilitiesRub": 22000000,
    "shortTermLiabilitiesRub": 105000000
  }
}
```

| Код | Строка |
|---|---|
| 1100 / 1200 | Внеоборотные / оборотные активы |
| 1300 | Капитал и резервы (собственный капитал) |
| 1400 / 1500 | Долгосрочные / краткосрочные обязательства |
| 1600 | Баланс (итого активы) |
| 2110 | Выручка |
| 2200 | Прибыль (убыток) от продаж |
| 2330 | Проценты к уплате |
| 2400 | Чистая прибыль (убыток) |

- `formType`: `FULL` или `SIMPLIFIED` (малый бизнес вправе сдавать упрощённую форму).
- `year` не указан → последний доступный.
- `404 STATEMENTS_NOT_FOUND`: у ИП, у самозанятого, у компании моложе года, за неподанный год.

Числа СтанкоПрома подобраны под расчёт ядра: чистая прибыль 30,7 млн/год ≈ 2,56 млн/мес, при платеже 377 тыс. DSCR ≈ 6,8.

### 5.3. `GET /api/v1/sme-status/{inn}` — Единый реестр МСП

**Реальный аналог:** rmsp.nalog.ru. Обновляется 10-го числа каждого месяца, новые компании попадают туда в следующем месяце после регистрации.

```json
{
  "meta": { "source": "FNS_RMSP", "dataActualAt": "2026-10-10", "…": "…" },
  "inn": "0012221117",
  "inRegistry": true,
  "category": "MICRO",
  "includedAt": "2026-08-10",
  "isNewlyCreated": true,
  "isSocialEnterprise": false
}
```

- `category`: `MICRO`, `SMALL`, `MEDIUM`.
- Нет в реестре → `200 {"inRegistry": false, "category": null, …}`.

Нужен для продуктов с господдержкой (они только для МСП) и для ленты новостей.

### 5.4. `POST /api/v1/self-employed/status` — статус НПД

**Реальный аналог:** открытый API ФНС `POST https://statusnpd.nalog.ru/api/v1/tracker/taxpayer_status`. **Этот эндпоинт повторяет реальный контракт один в один**, поэтому `meta` в теле нет (признак симуляции идёт заголовком `X-Mock-Simulated: true`).

Запрос:
```json
{ "inn": "001211122200", "requestDate": "2026-10-20" }
```

Ответ `200`:
```json
{ "status": true, "message": "001211122200 является плательщиком налога на профессиональный доход" }
```

- Не самозанятый → `{"status": false, "message": "001211122200 не является плательщиком налога на профессиональный доход"}`.
- У реального API жёсткий лимит частоты запросов. Через chaos (8.2) можно включить `429` с `Retry-After` и показать, что адаптер это обрабатывает.

### 5.5. `GET /api/v1/account-blocks/{inn}?bik=040000999` — блокировки счетов *(Should)*

**Реальный аналог:** сервис ФНС «БИ» (service.nalog.ru/bi.do), где по ИНН и БИК видны действующие решения о приостановлении операций по счетам.

```json
{
  "meta": { "source": "FNS_BLOCKS", "…": "…" },
  "inn": "0015557771",
  "checkedAt": "2026-10-20T09:12:03Z",
  "decisions": [
    { "number": "4512", "date": "2026-09-15", "taxAuthorityCode": "0003",
      "bik": "040000111", "reason": "TAX_DEBT_COLLECTION" }
  ]
}
```

`reason`: `NON_SUBMISSION_OF_DECLARATION`, `TAX_DEBT_COLLECTION`, `OTHER`. `bik` не передан → все решения по всем банкам.

### 5.6. Хранение — БД `mock_tax`

```
tax_profiles
  inn PK, tax_regimes JSONB,          -- [{code, year}]
  avg_headcount, headcount_year,
  tax_debt_rub, penalties_rub, fines_rub, debts_as_of,
  income_rub, expenses_rub, income_year,
  tax_offenses JSONB, risk_flags JSONB,
  data_actual_at, origin, scenario_code

taxes_paid
  inn FK, year, total_rub              PK (inn, year)

financial_statements                   -- одна строка на год
  inn FK, year, form_type, submitted_at,
  lines JSONB                          -- {"2110": 420000000, "2400": 30700000, ...}
  PK (inn, year)

sme_registry
  inn PK, category, included_at, is_newly_created, is_social_enterprise

npd_status
  inn PK, registered_at, deregistered_at NULL

account_blocks
  id PK, inn, number, date, tax_authority_code, bik, reason, lifted_at NULL
```

Поле `previous` в ответе `financials` берётся из строки за предыдущий год, отдельно не хранится. `sme_registry` и `npd_status` хранят только тех, кто в реестре; нет строки — значит `inRegistry: false` / `status: false`.

---

## 6. mock-credit-bureau — БКИ

**Реальный аналог.** НБКИ, ОКБ, Эквифакс. Банк — одновременно **пользователь** кредитной истории (запрашивает отчёты с согласия клиента) и **источник** (обязан передавать в БКИ сведения о заявках и выданных кредитах, 218-ФЗ). Мы моделируем обе роли.

Важные свойства, которые мок воспроизводит:
- без согласия субъекта отчёт не выдаётся;
- **каждый запрос оставляет след**: он появляется в информационной части следующих отчётов;
- «истории нет» — это нормальный ответ `200`;
- в отчёте **не видно название кредитора** (это закрытая часть, её видит только сам субъект);
- у ИП кредитная история личная, поэтому туда входят и его личные кредиты.

### 6.1. `POST /api/v1/credit-reports` — запросить отчёт

**Запрос:**

```json
{
  "subject": {
    "type": "LEGAL_ENTITY",
    "inn": "0015557771",
    "ogrn": "1190000007890",
    "name": "ООО «Ромашка»"
  },
  "consent": {
    "consentId": "cns_01JAK8M2W7",
    "subjectInn": "0015557771",
    "signedAt": "2026-10-20T09:05:41Z",
    "validUntil": "2027-04-20",
    "purpose": "LOAN_APPLICATION",
    "signMethod": "SIMPLE_ESIGN",
    "signerInn": "001310000436",
    "textVersion": "bki-consent-v1"
  },
  "purpose": "LOAN_APPLICATION",
  "applicationRef": "APP-2026-000123"
}
```

Для физлица (директор, владелец-поручитель, ИП как человек):

```json
"subject": {
  "type": "PERSON",
  "inn": "001310000436",
  "lastName": "Морозов", "firstName": "Олег", "middleName": "Викторович",
  "birthDate": "1981-05-14"
}
```

В реальности человека идентифицируют по паспорту. Мы упрощаем до ИНН + ФИО + даты рождения.

**Проверка согласия** (по порядку, первая неудача → `403`):

| `code` | Условие |
|---|---|
| `CONSENT_MISSING` | Нет блока `consent` |
| `CONSENT_SUBJECT_MISMATCH` | `consent.subjectInn` ≠ `subject.inn` |
| `CONSENT_NOT_YET_VALID` | `signedAt` в будущем |
| `CONSENT_EXPIRED` | `validUntil` < сегодня (согласие действует 6 месяцев) |
| `CONSENT_PURPOSE_MISMATCH` | `consent.purpose` ≠ `purpose` |

**Ответ `200`:**

```json
{
  "meta": { "source": "CREDIT_BUREAU", "…": "…" },
  "reportId": "rep_01JAK9ZQ1R",
  "generatedAt": "2026-10-20T09:12:05Z",
  "matchStatus": "MATCHED",
  "subject": { "type": "LEGAL_ENTITY", "inn": "0015557771", "ogrn": "1190000007890", "name": "ООО «Ромашка»" },
  "hasHistory": true,
  "summary": {
    "activeObligations": 2,
    "closedObligations": 3,
    "totalDebtRub": 4200000,
    "monthlyPaymentsRub": 310000,
    "currentOverdueRub": 180000,
    "currentOverdueDays": 94,
    "maxOverdueDays24m": 94,
    "restructurings24m": 0,
    "inquiries30d": 6,
    "inquiries30dExcludingOwn": 6,
    "rejectedApplications90d": 2,
    "historyLengthMonths": 84
  },
  "obligations": [
    {
      "uid": "6f1c2a8e-4b7d-4f0a-9c3e-2d5b8a1f7e60-4",
      "kind": "LOAN",
      "role": "BORROWER",
      "openedAt": "2024-02-01",
      "plannedCloseAt": "2027-02-01",
      "closedAt": null,
      "amountRub": 3000000,
      "balanceRub": 2100000,
      "monthlyPaymentRub": 140000,
      "overdueRub": 180000,
      "overdueDays": 94,
      "status": "ACTIVE",
      "secured": false,
      "paymentHistory": [
        { "month": "2026-03", "status": "OK" },
        { "month": "2026-04", "status": "OK" },
        { "month": "2026-05", "status": "OK" },
        { "month": "2026-06", "status": "D1_29" },
        { "month": "2026-07", "status": "D30_59" },
        { "month": "2026-08", "status": "D60_89" },
        { "month": "2026-09", "status": "D90_119" }
      ]
    }
  ],
  "inquiries": [
    { "date": "2026-10-20", "userType": "BANK", "purpose": "LOAN_APPLICATION", "isOwn": true },
    { "date": "2026-10-14", "userType": "BANK", "purpose": "LOAN_APPLICATION", "isOwn": false }
  ],
  "applications": [
    { "date": "2026-10-14", "kind": "LOAN", "amountRub": 2000000, "decision": "REJECTED", "decisionDate": "2026-10-15" }
  ],
  "bankruptcies": [],
  "bureauScore": { "value": 512, "scaleMin": 300, "scaleMax": 850, "model": "SIM-B2B-1" }
}
```

**Перечисления:**

| Поле | Значения |
|---|---|
| `matchStatus` | `MATCHED`, `NOT_FOUND` (тогда `hasHistory: false`, всё остальное пустое) |
| `obligations[].kind` | `LOAN`, `CREDIT_LINE`, `OVERDRAFT`, `CREDIT_CARD`, `LEASING`, `GUARANTEE` (банковская гарантия), `SURETY` (клиент поручитель по чужому долгу) |
| `obligations[].role` | `BORROWER`, `CO_BORROWER`, `GUARANTOR` |
| `obligations[].status` | `ACTIVE`, `CLOSED`, `RESTRUCTURED`, `SOLD_TO_COLLECTORS`, `WRITTEN_OFF`, `IN_COURT` |
| `paymentHistory[].status` | `OK`, `D1_29`, `D30_59`, `D60_89`, `D90_119`, `D120_PLUS`, `NO_DATA`. Соответствует шкале своевременности платежей в форматах БКИ |
| `inquiries[].userType` | `BANK`, `MFO`, `LEASING`, `INSURER`, `OTHER` |
| `applications[].decision` | `APPROVED`, `REJECTED`, `PENDING`, `WITHDRAWN` |

**`uid`** — уникальный идентификатор договора (УИд). В реальности его присваивает банк-кредитор: UUID плюс контрольный символ через дефис. Мы генерируем в том же формате.

**`isOwn` и `inquiries30dExcludingOwn`.** Запросы нашего банка помечаются. Без этого каждый прогон демо добавлял бы Соколовой запрос в БКИ, и через 3 прогона её грейд падал бы. Ядро считает фактор «запросы за 30 дней» по `inquiries30dExcludingOwn`.

**`bureauScore`** — иллюстрация того, что бюро продают собственную оценку. Ядро её **показывает андеррайтеру, но решение по ней не принимает**.

**Побочный эффект:** запрос записывается в `inquiries`, а отчёт целиком — в `reports` (по нему ответ потом можно воспроизвести).

### 6.2. `GET /api/v1/credit-reports/{reportId}`

Вернуть ранее выданный отчёт без нового запроса в историю. Нужен для карточки андеррайтера и аудита. `404 REPORT_NOT_FOUND`.

### 6.3. `POST /api/v1/submissions` — банк передаёт сведения в БКИ

Заголовок `Idempotency-Key` обязателен. `api` вызывает этот эндпоинт **из outbox**: заявку не задерживает, при сбое повторяет с тем же ключом.

```json
{ "eventId": "evt_01JAKA1", "eventType": "APPLICATION_REGISTERED", "occurredAt": "2026-10-20T09:11:00Z",
  "subject": { "type": "LEGAL_ENTITY", "inn": "0012345673" },
  "application": { "ref": "APP-2026-000124", "kind": "LOAN", "amountRub": 8000000, "termMonths": 12 } }
```

```json
{ "eventId": "evt_01JAKA2", "eventType": "APPLICATION_DECIDED", "occurredAt": "2026-10-20T09:14:00Z",
  "subject": { "type": "LEGAL_ENTITY", "inn": "0012345673" },
  "application": { "ref": "APP-2026-000124", "decision": "APPROVED" } }
```

```json
{ "eventId": "evt_01JAKA3", "eventType": "OBLIGATION_OPENED", "occurredAt": "2026-10-21T12:00:00Z",
  "subject": { "type": "LEGAL_ENTITY", "inn": "0012345673" },
  "obligation": { "uid": "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed-7", "kind": "LOAN", "role": "BORROWER",
                  "openedAt": "2026-10-21", "plannedCloseAt": "2027-10-21",
                  "amountRub": 8000000, "monthlyPaymentRub": 133000, "secured": false } }
```

| `eventType` | Что меняет в БКИ |
|---|---|
| `APPLICATION_REGISTERED` | Запись в `applications` со статусом `PENDING` |
| `APPLICATION_DECIDED` | `decision`: `APPROVED` / `REJECTED` / `WITHDRAWN`. Встречное предложение для БКИ — это `APPROVED` на других условиях, если клиент принял, или `WITHDRAWN`, если отказался |
| `OBLIGATION_OPENED` | Новое обязательство в `obligations` (`origin = RUNTIME`) |
| `OBLIGATION_CLOSED` *(Could)* | Закрытие |

Ответ `202 {"submissionId": "sub_…", "status": "ACCEPTED"}`. Ошибки: `400 VALIDATION_ERROR`, `404 APPLICATION_NOT_FOUND` (решение по незарегистрированной заявке), `409 IDEMPOTENCY_KEY_REUSED`.

**Зачем это на демо:** СнабКонтракт получил кредит → андеррайтер открывает новую заявку того же клиента → в отчёте БКИ уже есть наш кредит, а нагрузка выросла. Система ведёт себя как настоящая.

### 6.4. Хранение — БД `mock_bki`

```
subjects
  id PK, type (LEGAL_ENTITY|PERSON), inn UNIQUE, ogrn, name, last_name, first_name,
  middle_name, birth_date

obligations
  id PK, subject_id FK, uid UNIQUE, kind, role,
  opened_at, planned_close_at, closed_at, amount_rub, balance_rub, monthly_payment_rub,
  overdue_rub, overdue_days, status, secured, payment_history JSONB  -- [{month,status}]

inquiries
  id PK, subject_id FK, inquired_at, user_name, user_type, purpose, is_own, report_id FK NULL

applications_info
  id PK, subject_id FK, application_ref, applied_at, kind, amount_rub,
  decision, decided_at
  UNIQUE (subject_id, application_ref)

bankruptcies
  id PK, subject_id FK, case_number, started_at, completed_at, status

reports
  id PK, subject_id FK NULL, generated_at, purpose, application_ref,
  consent JSONB,          -- реквизиты согласия храним вместе с отчётом
  response JSONB          -- снимок ответа целиком

submissions
  id PK, event_id UNIQUE, event_type, payload JSONB, received_at, status

idempotency_keys
  key PK, endpoint, request_hash, response_status, response_body JSONB, created_at
```

Во всех таблицах, кроме `reports`, `submissions` и `idempotency_keys`, есть `origin` и `scenario_code` (см. 3.2). Запросы в БКИ и сведения от банка — `RUNTIME`.

`summary` не хранится, а считается при каждом запросе из `obligations`, `inquiries` и `applications_info` на дату `MOCK_TODAY`.

---

## 7. mock-bank-core — АБС и комплаенс

**Реальный аналог.** Автоматизированная банковская система (ЦФТ, Diasoft и т.п.): клиенты, счета, проводки, кредиты. Плюс два комплаенс-источника, которые банк держит у себя: **перечень Росфинмониторинга** (банк регулярно скачивает его из личного кабинета) и уровни риска **платформы ЦБ «Знай своего клиента»** (зелёный / жёлтый / красный, с 2022 года).

### 7.1. `GET /api/v1/customers/{inn}` — клиент ли нашего банка

```json
{
  "meta": { "source": "BANK_CORE", "…": "…" },
  "customerId": "cus_000017",
  "inn": "001234567887",
  "type": "INDIVIDUAL_ENTREPRENEUR",
  "name": "ИП Соколова Анна Сергеевна",
  "customerSince": "2023-05-02",
  "accounts": [
    { "number": "40802810100000001234", "type": "SETTLEMENT", "currency": "RUB",
      "status": "OPEN", "openedAt": "2023-05-02", "balanceRub": 412300 }
  ]
}
```

`404 CUSTOMER_NOT_FOUND` — не клиент (Гарипов, СтанкоПром и т.д.).

**Номера счетов настоящие по структуре**: 20 цифр, балансовый счёт `40702` (организация) / `40802` (ИП) / `45206` (кредит организации) / `45406` (кредит ИП), валюта `810`, контрольный ключ по БИК по алгоритму ЦБ. БИК синтетический (`BANK_BIK=040000999`).

### 7.2. `GET /api/v1/customers/{inn}/turnover?months=12` — обороты

Как договорились: **только месячные агрегаты по расчётному счёту бизнеса**, без отдельных операций. Личных счетов в моке нет вообще.

```json
{
  "meta": { "source": "BANK_CORE", "…": "…" },
  "inn": "001234567887",
  "accountNumbers": ["40802810100000001234"],
  "months": [
    { "month": "2025-10", "incomingRub": 861000, "incomingNetRub": 855000, "outgoingRub": 790000,
      "counterpartiesIn": 198, "counterpartiesOut": 23 },
    { "month": "2026-09", "incomingRub": 912000, "incomingNetRub": 905000, "outgoingRub": 845000,
      "counterpartiesIn": 214, "counterpartiesOut": 25 }
  ]
}
```

- `incomingNetRub` — поступления **без** переводов самому себе и полученных кредитов. Выданный нами кредит сюда тоже не попадает.
- `months` от 1 до 24, по умолчанию 12; только полные месяцы.
- Средние, тренды и падения считает ядро, не мок.
- `404 CUSTOMER_NOT_FOUND`.

Согласие клиента на использование оборотов проверяет `api` до вызова. АБС — внутренняя система, она согласия не проверяет, а `api` пишет каждый такой вызов в аудит.

### 7.3. `POST /api/v1/customers/{inn}/accounts` — открыть расчётный счёт *(Should)*

Нужен, когда кредит одобрен не-клиенту (Гарипов): деньги некуда зачислять. В реальности это отдельный процесс с идентификацией, у нас мгновенно. `Idempotency-Key` обязателен.

```json
{ "type": "SETTLEMENT", "currency": "RUB",
  "customer": { "type": "INDIVIDUAL_ENTREPRENEUR", "name": "ИП Гарипов Рустам Ильдарович" } }
```

`201` → объект `account` как в 7.1 (если клиента не было, он тоже создаётся). `409 ACCOUNT_ALREADY_EXISTS`, если расчётный счёт уже открыт.

### 7.4. `POST /api/v1/disbursements` — выдать кредит

Последний шаг конвейера после подписания. `Idempotency-Key` обязателен: повтор после таймаута **не должен выдать деньги дважды**.

```json
{
  "applicationRef": "APP-2026-000123",
  "customerInn": "001234567887",
  "contract": { "number": "КД-2026-000123", "uid": "6f1c2a8e-4b7d-4f0a-9c3e-2d5b8a1f7e60-4", "signedAt": "2026-10-20T10:01:00Z" },
  "product": { "code": "EXPRESS", "name": "Экспресс-кредит" },
  "kind": "LOAN",
  "amountRub": 500000,
  "limitRub": null,
  "termMonths": 12,
  "ratePercent": 24.0,
  "repaymentType": "ANNUITY",
  "settlementAccount": "40802810100000001234"
}
```

Ответ `201`:

```json
{
  "meta": { "source": "BANK_CORE", "…": "…" },
  "disbursementId": "dsb_01JAKB7",
  "status": "COMPLETED",
  "loanId": "loan_000041",
  "loanAccount": "45406810500000000041",
  "settlementAccount": "40802810100000001234",
  "amountRub": 500000,
  "valueDate": "2026-10-20",
  "postings": [
    { "debit": "45406810500000000041", "credit": "40802810100000001234", "amountRub": 500000,
      "purpose": "Выдача кредита по договору № КД-2026-000123 от 20.10.2026. НДС не облагается" }
  ],
  "settlementBalanceRub": 912300
}
```

| Поле | Значения |
|---|---|
| `kind` | `LOAN` (разовая выдача), `CREDIT_LINE` (открывается лимит `limitRub`, `amountRub` — первый транш, может быть 0), `OVERDRAFT` (только лимит) |
| `repaymentType` | `ANNUITY`, `BULLET` (проценты ежемесячно, долг в конце — кредит под контракт), `REVOLVING` (линия, овердрафт) |

Ошибки:

| HTTP | `code` | Когда |
|---|---|---|
| 404 | `CUSTOMER_NOT_FOUND` | Не клиент. Сначала 7.3 |
| 409 | `ACCOUNT_NOT_FOUND` | Счёт не принадлежит клиенту |
| 409 | `ACCOUNT_BLOCKED` | Счёт заблокирован |
| 409 | `ALREADY_DISBURSED` | По этой `applicationRef` уже была выдача с другим ключом |
| 422 | `VALIDATION_ERROR` | Сумма ≤ 0, срок ≤ 0 и т.п. |

График платежей **считает `api`**, а не АБС: это продуктовая логика, и её легче показать и протестировать в ядре.

### 7.5. Чтение после выдачи

| Запрос | Ответ |
|---|---|
| `GET /api/v1/accounts/{number}` | Счёт, остаток, последние 20 проводок (только созданные симулятором). Для кабинета: «деньги на счёте» |
| `GET /api/v1/loans/{loanId}` | Кредит: сумма/лимит, остаток долга, статус `ACTIVE`/`CLOSED` |
| `GET /api/v1/customers/{inn}/loans` | Наши кредиты клиенту (внутренняя кредитная история). Ядро учитывает их в долговой нагрузке, если БКИ ещё не обновилось |

### 7.6. `POST /api/v1/compliance/screening` — проверка по спискам

Один вызов проверяет всех участников заявки: компанию, директора, учредителей.

```json
{
  "subjects": [
    { "inn": "0017654322", "role": "COMPANY" },
    { "inn": "001310000115", "role": "DIRECTOR" },
    { "inn": "001310000115", "role": "FOUNDER" }
  ]
}
```

```json
{
  "meta": { "source": "COMPLIANCE", "…": "…" },
  "screeningId": "scr_01JAKA9",
  "overall": "CLEAR",
  "results": [
    { "inn": "0017654322", "role": "COMPANY",
      "amlList": { "listed": false, "listName": null },
      "zsk": { "riskLevel": "GREEN", "assessedAt": "2026-10-01" },
      "internalStopList": { "listed": false, "reason": null } },
    { "inn": "001310000115", "role": "DIRECTOR",
      "amlList": { "listed": false, "listName": null },
      "zsk": null,
      "internalStopList": { "listed": false, "reason": null } }
  ]
}
```

- `overall`: `CLEAR` или `HIT` (хоть одно совпадение).
- `amlList.listName`: `ROSFINMONITORING_TERRORISM_EXTREMISM`, `MVK_FREEZE`.
- `zsk` есть только у компаний и ИП, у физлиц `null`. `riskLevel`: `GREEN`, `YELLOW`, `RED`.
- В MVP стоп-фактор только `AML_LIST`. `zsk = RED` и внутренний стоп-лист есть в контракте для «Развития».

### 7.7. Хранение — БД `mock_bank_core`

```
customers
  id PK, inn UNIQUE, type, name, customer_since

accounts
  number PK (20 цифр), customer_id FK, type (SETTLEMENT|LOAN), currency,
  status (OPEN|BLOCKED|CLOSED), opened_at, balance_rub BIGINT

monthly_turnover                      -- только агрегаты, операций нет
  customer_id FK, month DATE, incoming_rub, incoming_net_rub, outgoing_rub,
  counterparties_in, counterparties_out
  PK (customer_id, month)

loans
  id PK, customer_id FK, application_ref UNIQUE, contract_number, contract_uid,
  product_code, kind, amount_rub, limit_rub, term_months, rate_percent,
  repayment_type, loan_account FK, settlement_account FK, status, disbursed_at

postings                              -- проводки, которые делает симулятор
  id PK, debit_account, credit_account, amount_rub, purpose, value_date,
  loan_id FK NULL, created_at

compliance_lists
  inn, list_type (AML|INTERNAL_STOP), list_name, reason, added_at
  PK (inn, list_type)

zsk_ratings
  inn PK, risk_level, assessed_at

idempotency_keys
  key PK, endpoint, request_hash, response_status, response_body JSONB, created_at
```

В `customers`, `accounts`, `monthly_turnover`, `loans`, `compliance_lists`, `zsk_ratings` есть `origin` и `scenario_code` (см. 3.2). Счета, открытые через 7.3, и всё, что создаёт выдача, — `RUNTIME`.

Выдача — **одна транзакция БД**: проводка, остаток расчётного счёта, кредит, ссудный счёт и ключ идемпотентности. Либо всё, либо ничего.

---

## 8. Служебные эндпоинты: health, chaos, админ-API данных

Есть у всех четырёх моков. Всё под `/admin/*` требует `X-Admin-Key`. На `/health/*` и `/admin/*` chaos и латентность не действуют: сломанный для демо мок всё равно можно наполнить и починить.

### 8.1. Здоровье

| Запрос | Ответ |
|---|---|
| `GET /health/live` | `200 {"status":"ok"}`, пока процесс жив |
| `GET /health/ready` | `200`, если БД доступна и миграции применены, иначе `503`. На него смотрит `healthcheck` в compose. У `mock-scenarios` ещё и стартовая синхронизация закончена (10.6) |

### 8.2. Chaos — управляемые сбои

`GET /admin/chaos` — текущий режим. `PUT /admin/chaos`:

```json
{
  "mode": "ERROR",
  "errorRate": 0.5,
  "latencyMs": null,
  "paths": ["/api/v1/credit-reports"],
  "rateLimitPerMinute": null,
  "until": "2026-10-20T10:00:00Z"
}
```

| `mode` | Поведение |
|---|---|
| `OK` | Обычная работа с латентностью из `MOCK_LATENCY_MS` |
| `SLOW` | Задержка `latencyMs`, ответ правильный. Показывает таймауты адаптера |
| `ERROR` | `503 SERVICE_UNAVAILABLE` с вероятностью `errorRate`. Показывает retry |
| `DOWN` | Всегда `503`. Показывает circuit breaker и уход на ручную проверку |
| `TIMEOUT` | Подвешивает ответ на 60 с. Проверяет, что у клиента настоящий таймаут |

- `paths` — сломать только часть (например, только отчёты БКИ, а submissions оставить); `null` — все `/api/v1/*`.
- `rateLimitPerMinute` — включить `429` с `Retry-After` (имитация лимитов реального API ФНС).
- `until` — автоматически вернуть `OK` (чтобы демо не осталось сломанным).
- Режим chaos — это настройка, а не тестовые данные, поэтому хранится в памяти процесса. Рестарт возвращает `OK`, и это правильно: после перезапуска стенд должен быть исправным.

### 8.3. Админ-API данных

Через него тестовые данные создаются, правятся и удаляются. Его вызывают сервис сценариев, тесты и человек через Swagger UI. **`api` его никогда не вызывает**: в жизни банк не может «записать компанию в ЕГРЮЛ».

Набор одинаковый у всех четырёх моков:

| Запрос | Что делает |
|---|---|
| `PUT /admin/subjects/{inn}` | Создать или **полностью заменить** данные субъекта в этой системе. Заголовок `X-Scenario-Code` проставляет `scenario_code`, `origin = SCENARIO` |
| `PATCH /admin/subjects/{inn}` | Частичная правка (JSON Merge Patch, RFC 7396): сменить статус, добавить долг, поменять обороты |
| `GET /admin/subjects/{inn}` | Всё, что система знает о субъекте, включая `RUNTIME`-записи (запросы в БКИ, выдачи) |
| `GET /admin/subjects?scenario=&origin=&limit=&offset=` | Список субъектов |
| `DELETE /admin/subjects/{inn}` | Удалить субъекта со всеми записями, включая `RUNTIME` |
| `GET /admin/scenarios` | Какие `scenario_code` есть в этой системе и сколько у каждого субъектов. Нужен сервису сценариев для сверки при старте |
| `DELETE /admin/scenarios/{code}` | Удалить всё, что создано этим сценарием, со всеми `RUNTIME`-записями |
| `POST /admin/wipe` | Очистить всю базу мока (справочники вроде ОКВЭД не трогает) |

**Тело `PUT` — в тех же терминах, что и ответ бизнес-API, только без `meta`.** Агенту не нужно придумывать вторую схему, а человеку в Swagger понятно, что писать:

| Мок | Тело `PUT /admin/subjects/{inn}` |
|---|---|
| registry | `{ "entity": <как ответ GET companies/{inn}>, "persons": [{inn, lastName, firstName, middleName, birthDate}] }` |
| tax | `{ "taxProfile": <как tax-profile>, "financials": [{year, formType, submittedAt, lines}], "sme": {…} \| null, "npd": {registeredAt} \| null, "accountBlocks": [ … ] }` |
| bki | `{ "subject": {…}, "obligations": [ … ], "inquiries": [ … ], "applications": [ … ], "bankruptcies": [ … ] }`. Физлицо (директор) — отдельный субъект со своим ИНН |
| bank-core | `{ "customer": {…} \| null, "accounts": [ … ], "turnover": [ {month, …} ], "compliance": { "aml": …, "zsk": …, "internalStopList": … } }`. Номер счёта можно не указывать — мок сгенерирует с правильным ключом |

Ответы: `200`/`201` с сохранённым объектом, `422 VALIDATION_ERROR` с понятной причиной (например, «у ИП не может быть КПП»), `404 SUBJECT_NOT_FOUND` для `PATCH`/`DELETE`.

Пример ручной правки через Swagger: «Соколову признали банкротом» — `PATCH /admin/subjects/001234567887` в `mock-registry` с телом `{"entity": {"status": {"code": "BANKRUPT"}}}`. Следующая заявка Соколовой получит отказ.

### 8.4. Сброс

- `POST /admin/wipe` в одном моке чистит только его.
- Вернуть стенд в исходное состояние целиком — `POST /api/v1/scenarios/reset` в `mock-scenarios` (раздел 10.4). Он чистит все 4 мока и применяет сценарии заново.
- `POST /demo/reset` в `api` (делает команда, не этот агент) будет вызывать reset сценариев и чистить базу `api`.

---

## 9. Как `api` работает с моками

### 9.1. Кто, когда и что вызывает

```mermaid
sequenceDiagram
    autonumber
    participant UI as Кабинет клиента
    participant API as api
    participant REG as mock-registry
    participant TAX as mock-tax
    participant ABS as mock-bank-core
    participant BKI as mock-credit-bureau

    Note over UI,API: Ввод ИНН (автозаполнение)
    UI->>API: GET /company/lookup/{inn}
    API->>REG: GET /companies/{inn}
    alt 404 и ИНН 12 цифр
        API->>REG: GET /persons/{inn}/roles
        API->>TAX: POST /self-employed/status
    end
    API->>TAX: GET /sme-status/{inn}
    API-->>UI: карточка + источник и дата каждого поля

    Note over UI,API: Отправка заявки → конвейер
    UI->>API: POST /applications/{id}/submit
    API->>BKI: POST /submissions (APPLICATION_REGISTERED, через outbox)
    par Бесплатные проверки
        API->>REG: GET /companies/{inn}
        API->>TAX: GET /tax-profile/{inn}
        API->>TAX: GET /financials/{inn}
        API->>TAX: GET /account-blocks/{inn}
        API->>ABS: POST /compliance/screening
        API->>ABS: GET /customers/{inn}/turnover
    end
    Note over API: Стоп-факторы по бесплатным данным.<br/>Сработал → отказ, в БКИ не идём
    API->>BKI: POST /credit-reports (компания)
    API->>BKI: POST /credit-reports (директор / ИП)
    Note over API: Скоринг → решение
    API->>BKI: POST /submissions (APPLICATION_DECIDED)

    Note over UI,API: Подписание и выдача
    UI->>API: POST /applications/{id}/sign
    opt Не клиент банка
        API->>ABS: POST /customers/{inn}/accounts
    end
    API->>ABS: POST /disbursements (Idempotency-Key)
    API->>BKI: POST /submissions (OBLIGATION_OPENED)
    API-->>UI: SSE: «Деньги зачислены»
```

### 9.2. Адаптеры

Под каждый мок в `api` свой адаптер (`api/app/integrations/<system>/`): HTTP-клиент `httpx.AsyncClient`, свои DTO и маппинг во внутреннюю модель. **Код и схемы моков `api` не импортирует**: это разные системы, интеграция только по контракту. Внутренние модели (`CompanyProfile`, `CreditHistory`, `Turnover`) не зависят от формата внешней системы. Поменяется формат БКИ — правится только адаптер.

| Система | Таймаут | Повторы | Circuit breaker | Кэш в `api` |
|---|---|---|---|---|
| registry | 2 с | 2, экспонента + jitter | 5 ошибок за 30 с → открыт на 30 с | 24 ч |
| tax | 2 с | 2 | так же | 24 ч, отчётность 7 дней |
| credit-bureau: отчёт | 5 с | 1 | так же | Не кэшируем между заявками. Внутри одной заявки отчёт переиспользуем до 30 дней: каждый запрос платный |
| credit-bureau: submissions | 5 с | outbox, до успеха | — | — |
| bank-core: чтение | 1 с | 2 | так же | обороты 1 ч |
| bank-core: выдача | 5 с | outbox, до успеха, **тот же `Idempotency-Key`** | — | — |

Повторяем только `GET` и `POST` с `Idempotency-Key`. `POST /credit-reports` повторяем один раз, и только при `503` или обрыве соединения до ответа.

### 9.3. Что делает конвейер, если система недоступна

| Система упала | На этапе | Поведение |
|---|---|---|
| registry | Автозаполнение | Клиент вводит данные вручную, поля помечены «не подтверждено реестром» |
| registry, tax | Решение | Повторы → заявка уходит в `MANUAL_REVIEW` с флагом `SOURCE_UNAVAILABLE`. Андеррайтер видит, какой источник не ответил, и может перезапросить |
| credit-bureau | Решение | То же: `MANUAL_REVIEW`. **Главный сценарий демо** «уронили БКИ — конвейер не упал» |
| bank-core: обороты | Решение | Берём выручку из отчётности или выписки. Нет ни того, ни другого → `NEEDS_INFO` |
| bank-core: выдача | Выдача | Статус «Выдача в обработке», outbox повторяет. Повторы безопасны благодаря идемпотентности |
| credit-bureau: submissions | Любой | Не блокирует заявку. Outbox доставит позже |

### 9.4. Что хранит `api` об интеграциях

```
consents                              -- согласия хранит банк, в БКИ уходят реквизиты
  id PK, application_id FK, subject_inn, subject_type, kind (BKI|TURNOVER|PERSONAL_DATA),
  purpose, text_version, text_hash, signed_at, valid_until, signer_user_id,
  sign_method (SIMPLE_ESIGN), sign_code_hash, revoked_at

source_snapshots                      -- факты, на которых принято решение
  id PK, application_id FK NULL, system, resource, subject_inn,
  payload JSONB, payload_hash, data_actual_at, retrieved_at, expires_at, request_id

integration_calls                     -- журнал каждого вызова
  id PK, system, method, path, subject_inn_masked, status_code, error_code,
  duration_ms, attempt, circuit_state, request_id, application_id, created_at

outbox
  id PK, aggregate_id, event_type, target_system, payload JSONB,
  idempotency_key, attempts, next_attempt_at, status, last_error, created_at
```

Снимок решения в ядре ссылается на `source_snapshots.id`. Через месяц можно показать, на каких данных из какой системы и от какой даты принято решение.

---

## 10. Тестовые данные: сервис сценариев `mock-scenarios`

### 10.1. Зачем отдельный сервис

Тестовая компания живёт сразу в четырёх системах: в ЕГРЮЛ, в ФНС, в БКИ и (если клиент) в АБС. Данные должны сходиться: выручка в отчётности ≈ обороты по счёту, директор в БКИ = директор в ЕГРЮЛ, категория МСП соответствует выручке. Если заполнять моки по отдельности, руками или скриптами, они быстро разъедутся.

Поэтому есть **сценарий** — одно описание компании, — и сервис, который:
1. хранит сценарии в своей базе;
2. **разворачивает** их: генерирует ИНН, ОГРН, ФИО, номера счетов, обороты по месяцам, историю платежей;
3. **раскладывает** по четырём мокам через их админ-API (8.3);
4. сам заполняет моки при старте, если в них пусто.

Сервис — тестовая инфраструктура, а не имитация внешней системы. В бизнес-процессе `api` он не участвует.

### 10.2. Формат сценария: параметры вместо сырых данных

Сценарий описывает компанию **крупными параметрами**, а не таблицами. Всё, что не указано, берётся из пресета, а дальше генерируется. Так компания под проверку жюри создаётся одним запросом:

```json
POST /api/v1/scenarios
{
  "title": "ООО 2 года, выручка 5 млн/мес, просрочка 40 дней",
  "preset": "LLC_HEALTHY",
  "company": { "ageMonths": 24, "okved": "47.19", "regionCode": "77" },
  "finance": { "avgMonthlyRevenueRub": 5000000 },
  "bki": { "company": { "currentOverdueDays": 40 } }
}
```

Ответ `201`:

```json
{
  "code": "custom-7f3a",
  "inn": "0019384752",
  "ogrn": "1240000019380",
  "shortName": "ООО «Альфа-Тест 7F3A»",
  "director": { "fullName": "Смирнов Павел Андреевич", "inn": "001387650028" },
  "applied": { "registry": "OK", "tax": "OK", "bki": "OK", "bankCore": "SKIPPED" },
  "expanded": { "…": "полные данные, которые ушли в каждый мок" }
}
```

**Параметры сценария** (все необязательные, кроме `title`):

| Блок | Параметры |
|---|---|
| верх | `code` (иначе сгенерируется), `title`, `preset`, `expectedOutcome` (для тестов `api`) |
| `company` | `form`: `IP` / `LLC` / `JSC` / `SELF_EMPLOYED`; `name`; `ageMonths` или `registrationDate`; `status`; `okved`; `regionCode`; `unreliableAddress`; `pendingExclusion` |
| `people` | `director`, `founders[]` (ФИО, дата рождения, доля; иначе генерируются). У ИП человек — сам предприниматель |
| `finance` | `avgMonthlyRevenueRub`; `revenueTrend`: `GROWTH` / `STABLE` / `DECLINE` и `trendPercent`; `seasonality`: `NONE` / `AGRO` / `RETAIL_Q4`; `netMarginPercent`; `hasStatements`; `taxRegime`; `headcount` |
| `tax` | `taxDebtRub`, `massAddress`, `massDirector`, `disqualifiedManagement`, `accountBlocked` |
| `bki.company`, `bki.director`, `bki.owner` | `historyYears` (0 — истории нет), `activeLoans[]` (`kind`, `amountRub`, `termMonths`, `ratePercent` или `monthlyPaymentRub`) или просто `monthlyPaymentsRub`, `currentOverdueDays`, `currentOverdueRub`, `pastMaxOverdueDays`, `restructurings24m`, `inquiries30d`, `rejectedApplications90d`, `bankruptcyYearsAgo`, `soldToCollectors` |
| `bank` | `isCustomer`, `customerSinceMonths`, `balanceRub` |
| `compliance` | `amlListed`: `COMPANY` / `DIRECTOR` / `null`; `zsk`; `internalStopList` |
| `raw` | Точные данные для конкретного мока, **перекрывают** сгенерированные: `raw.tax.financials`, `raw.bki.company.obligations` и т.п. Нужен встроенным персонам с выверенными цифрами |
| `users` | Учётки кабинета (`login`, `role`, ссылка на человека). **В моки не уходят**, их потом заберёт `api` через `GET /scenarios/{code}` |

**Пресеты** (`GET /api/v1/presets` возвращает их с параметрами по умолчанию):

| Пресет | Что по умолчанию |
|---|---|
| `IP_HEALTHY` | ИП 3 года, УСН 6%, выручка 800 тыс./мес, чистая личная история, клиент банка |
| `LLC_HEALTHY` | ООО 5 лет, ОСНО, выручка 10 млн/мес, отчётность, 1 кредит без просрочек, не клиент |
| `LLC_HIGH_DEBT_LOAD` | Как `LLC_HEALTHY`, но платежи по кредитам 70% денежного потока |
| `STARTUP` | ООО 3 месяца, АУСН, без истории, без отчётности |
| `SELF_EMPLOYED` | Самозанятый: только статус НПД |
| `PROBLEM_DEBTOR` | ООО с просрочкой 90+ и налоговым долгом |

### 10.3. Что сервис генерирует и как держит согласованность

**Генерация детерминирована**: случайность берёт seed из `code` сценария. Один и тот же сценарий всегда даёт те же ИНН, ФИО и цифры. Это важно для тестов и для переприменения.

| Что | Как |
|---|---|
| ИНН, ОГРН/ОГРНИП, КПП | Регион `00`, правильные контрольные суммы, проверка уникальности по базе сценариев. Год в ОГРН совпадает с датой регистрации |
| ФИО, даты рождения | Из встроенных списков имён; возраст директора 25–65 лет |
| Даты | Относительные (`ageMonths`, `-3M`) переводятся в абсолютные **при каждом применении**, поэтому персоны не стареют |
| Обороты по счёту | 12–24 месяца из `avgMonthlyRevenueRub` с трендом, сезонностью и шумом ±5% |
| Отчётность ГИР БО | Выручка за год ≈ сумма оборотов; чистая прибыль = выручка × `netMarginPercent`; баланс сходится (1600 = 1100 + 1200 = 1300 + 1400 + 1500) |
| Кредитная история | `historyYears` без активных кредитов → закрытый кредит без просрочек в прошлом. Из `currentOverdueDays` строится обязательство с историей платежей, которая честно доходит до этой просрочки (`OK … D1_29 → D30_59`). УИд в настоящем формате |
| Категория МСП | Считается по выручке и численности, если не указана |

**Правила согласованности** — нарушение даёт `422` с объяснением, а не тихо неверные данные:
- у ИП и самозанятого нет бухотчётности, КПП, директора и учредителей;
- самозанятого нет в ЕГРИП — только статус НПД;
- отчётности нет, если компании меньше года;
- кредитная история компании не старше компании (у людей может быть старше);
- выданные кредиты не могут иметь платёж больше суммы;
- `isCustomer: false` и `balanceRub` вместе — ошибка.

### 10.4. API сервиса

Все запросы требуют `X-Admin-Key`. Вся работа с данными идёт через Swagger UI (`http://localhost:<порт>/docs`) или коллекцию запросов.

| Запрос | Что делает |
|---|---|
| `GET /api/v1/presets` | Пресеты и их параметры по умолчанию |
| `POST /api/v1/scenarios/preview` | Развернуть сценарий **без сохранения**: посмотреть, что получится в каждом моке |
| `POST /api/v1/scenarios` | Создать и применить. `201` с ИНН и итогом по каждому моку |
| `GET /api/v1/scenarios?origin=BUILTIN\|CUSTOM` | Список: `code`, `title`, ИНН, `expectedOutcome`, статус применения |
| `GET /api/v1/scenarios/{code}` | Параметры, развёрнутые данные, учётки, журнал применений |
| `PATCH /api/v1/scenarios/{code}` | Поменять параметры и переприменить: компания пересоздаётся с новыми данными |
| `POST /api/v1/scenarios/{code}/apply` | Вернуть одну компанию в исходное состояние: стереть всё по ней во всех моках (включая выдачи и запросы в БКИ) и создать заново |
| `DELETE /api/v1/scenarios/{code}` | Удалить сценарий и его данные во всех моках. Встроенные удалить нельзя: `409 BUILTIN_SCENARIO` |
| `POST /api/v1/scenarios/reset` | `{"mode": "KEEP_CUSTOM"}` — очистить все 4 мока и применить все сценарии заново; `{"mode": "BUILTIN_ONLY"}` — то же, но пользовательские сценарии удаляются |

**Применение и откат.** Сценарий применяется по очереди в 4 мока (`PUT /admin/subjects/{inn}` с `X-Scenario-Code`). Если какой-то мок не ответил, уже записанное удаляется (`DELETE /admin/scenarios/{code}`), сценарий получает статус `FAILED`, ответ — `502 APPLY_FAILED` с указанием системы. Половинчатых компаний не бывает.

### 10.5. Встроенные сценарии

9 персон и 5 технических лежат в `builtin.py` **в том же формате, что и `POST /scenarios`**. У них заданы `code`, точные реквизиты и ФИО, а выверенные цифры (отчётность СтанкоПрома, просрочка Ромашки) — через `raw`. Всё прочее генерируется так же, как у пользовательских. У встроенных есть `builtinVersion`: если сценарий в коде поменяли, после пересборки он переприменится сам (10.6).

Пример встроенной персоны:

```json
{
  "code": "stankoprom",
  "title": "ООО «СтанкоПром» — крупная сумма с залогом, ручное рассмотрение",
  "builtinVersion": 1,
  "expectedOutcome": "MANUAL_REVIEW",
  "preset": "LLC_HEALTHY",
  "company": { "form": "LLC", "inn": "0017654322", "ogrn": "1170000004569", "kpp": "001701001",
               "name": "СтанкоПром", "registrationDate": "-9y7M", "okved": "25.62", "regionCode": "66" },
  "people": { "director": { "ref": "kuznetsov", "inn": "001310000115", "fullName": "Кузнецов Игорь Петрович",
                            "birthDate": "1979-02-11", "sharePercent": 100 } },
  "finance": { "avgMonthlyRevenueRub": 35000000, "taxRegime": "OSNO", "headcount": 60 },
  "bki": {
    "company":  { "historyYears": 6, "activeLoans": [] },
    "director": { "activeLoans": [ { "kind": "CREDIT_CARD", "amountRub": 300000, "monthlyPaymentRub": 4500 } ] }
  },
  "bank": { "isCustomer": false },
  "raw": { "tax": { "financials": [
    { "year": 2025, "formType": "FULL", "lines": { "1100": 182000000, "1200": 141000000, "1300": 196000000,
      "1400": 22000000, "1500": 105000000, "1600": 323000000, "2110": 420000000, "2200": 41500000,
      "2330": 1900000, "2400": 30700000 } },
    { "year": 2024, "formType": "FULL", "lines": { "1600": 299000000, "2110": 388000000, "2400": 27400000 } } ] } },
  "users": [
    { "login": "kuznetsov", "role": "DIRECTOR", "personRef": "kuznetsov" },
    { "login": "belova", "role": "ACCOUNTANT", "fullName": "Белова Ольга Николаевна", "inn": "001310000299", "powerOfAttorney": true }
  ]
}
```

**Что у каждой встроенной персоны в каждом моке:**

| Персона | registry | tax | bki | bank-core | Исход |
|---|---|---|---|---|---|
| **Соколова** (ИП) | ACTIVE, 3 г., 56.10 | УСН 6%, долгов нет | Чистая: 1 закрытый кредит, кредитка ~3 тыс./мес | **Клиент**, ~900 тыс./мес | ✅ Авто |
| **СнабКонтракт** | ACTIVE, 6 л., 46.46 | ОСНО, ГИР БО: выручка 180 млн, чистая прибыль ~14,4 млн | 2 активных кредита, платежи ~600 тыс./мес, без просрочек | **Клиент**, ~15 млн/мес | 🔄 Встречное |
| **СтанкоПром** | ACTIVE, 9 л., 25.62; директор Кузнецов | ОСНО, ГИР БО: выручка 420 млн, прибыль 30,7 млн | Компания: закрытый инвесткредит; Кузнецов: кредитка | Не клиент | 👤 Ручное |
| **Гарипов** (ИП) | ACTIVE, 5 л., 96.02 | Патент, ГИР БО `404` | Тонкое досье: 1 закрытый кредит 3 года назад | Не клиент → откроет счёт при выдаче | 📄 Нужна информация |
| **Ромашка** | ACTIVE, 7 л., 46.73 | УСН 15%, **налоговый долг 1,15 млн** (> 10% от ~7,9 млн/мес) | **Просрочка 94 дня**, 6 запросов за 30 дней, 2 отказа | Не клиент | ❌ Отказ |
| **Вектор** | **LIQUIDATING** + недостоверность адреса | УСН 6% | Есть, но до неё не доходим | Не клиент | ❌ Отказ до БКИ |
| **Орлов** (самозанятый) | **404** | НПД: `status: true` | — | — | ℹ️ Объяснение |
| **Заря** (АО) | ACTIVE, 24 г., 01.11 | ЕСХН, ГИР БО: выручка 1,4 млрд | Много кредитных линий за 10 лет, всё вовремя | Клиент, сезонные обороты | 👤 Ручное → ✅ |
| **Быстрый старт** | ACTIVE, **-3M**, 62.01 | АУСН | `hasHistory: false` | Не клиент | 🔄 Встречное (с поручительством) |

**Технические сценарии** (только для тестов стоп-факторов и флагов, учёток для демо у них нет). ИНН генерирует сам сервис:

| Персона | Что проверяет |
|---|---|
| `t-aml` | Директор в перечне Росфинмониторинга → `AML_LIST` |
| `t-gambling` | ОКВЭД 92.xx → `FORBIDDEN_INDUSTRY` |
| `t-mass` | `massAddress: true` → флаг `MASS_REGISTRATION` |
| `t-overdue-45` | Текущая просрочка 45 дней → флаг `OVERDUE_30_89` |
| `t-bankrupt` | Банкротство владельца 2 года назад → `BANKRUPTCY` |

ИНН и ОГРН всех персон из прошлых обсуждений проверены: контрольные суммы сходятся.


### 10.6. Автозаполнение при старте и после пересборки

При каждом старте `mock-scenarios`, до того как стать `ready`:

1. Применить свои миграции.
2. Записать встроенные сценарии из кода в свою базу: новых нет — добавить; `builtinVersion` в коде больше, чем в базе, — обновить и пометить «переприменить». Пользовательские не трогать.
3. Сверить с моками: для каждого сценария спросить у каждого мока `GET /admin/scenarios`. Где данных сценария нет (база мока пустая или пересоздана) — применить сценарий **только в этот мок**. Где есть — не трогать, чтобы не стереть то, что появилось в ходе работы (выданный кредит, запросы в БКИ).
4. Применить сценарии с пометкой «переприменить» (полностью, как `/apply`).

| Ситуация | Что произойдёт |
|---|---|
| Пересобрали образы, том Postgres цел | Данные на месте. Изменённые встроенные сценарии переприменятся |
| `docker compose down -v`, первый запуск у жюри | Базы пустые → все сценарии применятся сами за несколько секунд |
| Удалили базу одного мока | Данные досоздадутся только в нём |
| Демо «испортило» данные | `POST /api/v1/scenarios/reset` |
| Нужно вернуть одну компанию | `POST /api/v1/scenarios/{code}/apply` |
| Жюри хочет свой случай | `POST /api/v1/scenarios` через Swagger: пресет + 2–3 параметра |

Ничего запускать руками не нужно: обычный `docker compose up` всегда приводит стенд в рабочее состояние.

### 10.7. Хранение — БД `mock_scenarios`

```
scenarios
  code PK, title, origin (BUILTIN|CUSTOM), builtin_version NULL, expected_outcome,
  inn UNIQUE,
  spec JSONB,                         -- параметры, как их прислали
  expanded JSONB,                     -- развёрнутые данные последнего применения
  status (PENDING|APPLIED|PARTIAL|FAILED), needs_reapply, last_error,
  created_at, updated_at, applied_at

scenario_applications                 -- журнал: что и куда отправлялось
  id PK, scenario_code FK, system (REGISTRY|TAX|BKI|BANK_CORE),
  action (PUT|DELETE), http_status, error, at
```

Источник правды для **исходного** состояния компании — `spec`. Источник правды для **текущего** состояния — базы моков.

---

## 11. Тесты и артефакты сдачи

**Тесты моков** (`mocks/tests`, pytest + `httpx.AsyncClient`):
- для каждой встроенной персоны каждый эндпоинт отдаёт данные, согласованные со сценарием;
- `400` на неверный ИНН, `404`/`200 + false` по правилу из 2.4;
- БКИ: каждая из 5 причин `403` по согласию; запрос увеличивает `inquiries30d`; `isOwn` не влияет на `inquiries30dExcludingOwn`; `submissions` меняет следующий отчёт;
- АБС: повтор `disbursements` с тем же ключом не меняет остаток; другой ключ на ту же заявку → `409 ALREADY_DISBURSED`; номера счетов проходят проверку контрольного ключа;
- chaos: каждый режим, `paths`, `until`;
- админ-API: `PUT` → бизнес-`GET` отдаёт то же; `PATCH` меняет только указанное; `DELETE /admin/scenarios/{code}` удаляет и `RUNTIME`-записи; `422` на противоречивые данные;
- сценарии: развёртывание детерминировано (дважды один `code` → одинаковые данные); у сгенерированных ИНН, ОГРН и счетов верные контрольные суммы; каждое правило согласованности из 10.3 даёт `422`; сбой одного мока при применении откатывает остальные;
- стартовая синхронизация: пустые базы → всё заполнено; данные есть → `RUNTIME`-записи (выдача) не стёрты; `builtinVersion` поднят → сценарий переприменён;
- `scenarios/reset` в обоих режимах;
- контрактный тест: выгруженный OpenAPI совпадает с закоммиченным в `docs/api/` (CI падает, если контракт поменяли и не обновили документ).

**Артефакты для сдачи (стр. 7 кейса):**
- `docs/api/mock-registry.openapi.yaml`, `mock-tax…`, `mock-credit-bureau…`, `mock-bank-core…`;
- `docs/api/mock-scenarios.openapi.yaml`;
- коллекция Bruno `docs/api/collection/mocks/`: по запросу на каждую персону и каждую ошибку, сценарий «уронить БКИ», папка «Своя компания» с примерами `POST /scenarios` на каждый пресет;
- `THIRD_PARTY_NOTICES`, раздел «Смоделированные интеграции»: таблица из раздела 12.

---

## 12. Что упрощено по сравнению с реальностью

| В реальности | У нас | Что сохранили |
|---|---|---|
| ЕГРЮЛ/ЕГРИП через СМЭВ, XML, асинхронно (запрос → квитанция → ответ) | REST/JSON, синхронно | Состав полей, статусы, отметки о недостоверности, разделение ЕГРЮЛ/ЕГРИП |
| Аутентификация сертификатами (СМЭВ, mTLS в БКИ) | `X-Api-Key` на систему | Каждая система требует свой доступ |
| БКИ: XML-формат кредитного отчёта по нормативам ЦБ, идентификация физлица по паспорту | JSON, ИНН + ФИО + дата рождения | Части истории (титульная, основная, информационная), согласие, УИд, шкала просрочек, след от каждого запроса |
| Согласие на запрос в БКИ хранится у банка, проверяется при аудитах | Реквизиты согласия передаются в каждом запросе и проверяются моком | Без согласия отчёта нет |
| АБС с операциями по счёту | Только месячные агрегаты и проводки выдачи | Расчёт выручки по оборотам, реальная структура номеров счетов, идемпотентная выдача |
| Перечень Росфинмониторинга и ЗСК — отдельные внешние источники | Справочники внутри `mock-bank-core` | Проверка всех участников заявки |
| Открытие счёта — процесс с идентификацией | Мгновенно | Не-клиент не может получить деньги без счёта |
| Компанию нельзя «записать» в ЕГРЮЛ или БКИ | Админ-API у каждого мока и сервис сценариев, закрыты отдельным ключом, `api` их не вызывает | Бизнес-API моков такой же, как если бы данных никто не правил |
| Каждый запрос в БКИ платный | Бесплатно | Порядок проверок: бесплатные раньше платных; переиспользование отчёта в рамках заявки |

Все данные синтетические. Коды регионов в ИНН и ОГРН — `00` (такого региона нет), БИК синтетический, поэтому номера не могут совпасть с реальными компаниями и счетами.

---

## 13. Открытые вопросы

1. **Кто выверяет цифры встроенных персон** (`builtin.py`): человек на кредитной логике или владелец моков? Они должны сходиться с прогоном ядра.
2. **`account-blocks` (Should)** и **открытие счёта (Should)**: берём в MVP? Первое добавляет стоп-фактор почти бесплатно, без второго Гарипов не дойдёт до выдачи.
3. **Встречное предложение в БКИ**: передаём как `APPROVED` после того, как клиент его принял, или сразу `APPROVED` с другими условиями? Предлагаю первое.
4. **Учётки кабинета для пользовательских сценариев**: `api` будет забирать блок `users` из `GET /scenarios/{code}` и создавать учётку сам? Тогда жюри создаёт компанию и сразу входит под ней. Договориться с тем, кто делает `api`.
