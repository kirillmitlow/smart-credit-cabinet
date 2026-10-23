# API: как проверить работающий стенд

Сверено с main `78fda5e` 24.10.2026. [Назад к документации](../README.md).

## Адреса и схемы

| Сервис | Прямой локальный адрес | Сохранённая схема |
|---|---|---|
| API | http://127.0.0.1:8100 | [api.openapi.json](api.openapi.json) |
| registry | http://127.0.0.1:8101 | Живая `/openapi.json` |
| tax / ЕИС | http://127.0.0.1:8102 | Живая `/openapi.json` |
| credit-bureau | http://127.0.0.1:8103 | Живая `/openapi.json` |
| bank-core | http://127.0.0.1:8104 | Живая `/openapi.json` |
| scenarios | http://127.0.0.1:8105 | [mock-scenarios.openapi.yaml](mock-scenarios.openapi.yaml) |

У каждого сервиса `/docs` — Swagger, `/openapi.json` — текущая схема, `/health/ready` — готовность. Swagger загружает оформление с CDN; сами JSON-схемы можно читать без CDN. Файл scenarios содержит JSON, допустимый в YAML 1.2. Выгрузка остальных схем и генератор `make openapi` принадлежат владельцу кода; этот пакет их не меняет.

В браузере API вызывается через **http://localhost:8080/api**; nginx также принимает `/api/v1` и удаляет этот префикс. У прямого адреса `8100` маршруты идут от корня: `/applications`, а не `/api/v1/applications`. Изолированный стенд команды на **http://127.0.0.1:8090** — отдельная установка, не порт по умолчанию и не обещание его доступности на другом компьютере. Для него `apiUrl=http://127.0.0.1:8090/api`. Сохраняйте один hostname в пределах сессии: cookie от `localhost` не становится cookie для `127.0.0.1`.

## Postman v2.1

Импортируйте [postman_collection.json](postman_collection.json) через Import → File. Формат — [официальная схема v2.1](https://schema.getpostman.com/json/collection/v2.1.0/collection.json). В коллекции четыре независимые папки: Соколова, СнабКонтракт, Станкопром, Ромашка, плюс проверки пяти моков и предпросмотр компании. Полный путь использует реальные ручки входа, согласий, решения, предложения, подписи и кредита. Станкопром входит директором Кузнецовым, после ручного разбора банк L2 предлагает оборотные 10 млн на 12 месяцев без заданной ставки.

1. Запустите локальный стенд по [README](../../README.md). Для воспроизводимых чисел задайте `APP_TODAY=2026-10-21` перед запуском.
2. Оставьте стандартные переменные коллекции либо укажите свои `apiUrl`, `webOrigin` и прямые адреса моков. `webOrigin` — адрес web без `/api`. `mockAdminKey=dev-admin-key` — исключительно локальное значение из Compose. Облачный `demoCode` вводит владелец стенда, в экспорт его не сохраняйте.
3. Включите cookie jar. **Запускайте одну папку сценария целиком**, в Collection Runner установите Delay **1000 мс**. Первый запрос удаляет демо-заявки и кредиты **только выбранной персоны**; предупредите других участников этого стенда. Общий сброс коллекция не делает.
4. UUID компании/руководителя, requestId и коды берутся из ответов; согласия выбираются по `canSign`; вариант — по `recommended`. Банковские `version`, `engineDecisionId` и `evaluationRef` тоже получаются с сервера. Сохранённого постоянного кода нет.
5. Опрос решения и выдачи ограничен 60 попытками; неожиданный исход останавливает прогон с ошибкой. При ручном Send переходы Runner не действуют: повторяйте запрос ожидания до нужного статуса. `409 DEMO_RESET_IN_PROGRESS` при сбросе — повтор через секунду; `502 DEMO_RESET_FAILED` — ошибка, которую нужно разобрать, не считать успешным сбросом.

Повтор команды сохранения решения после потери ответа использует **то же тело и тот же** `decisionActionKey`. Изменённое тело с тем же ключом даст `409 IDEMPOTENCY_KEY_REUSED`. Если версия устарела, заново прочитайте карточку и рассчитайте условия; для нового действия удалите старый `decisionActionKey`, чтобы создать новый. Не применяйте новый ключ просто ради обхода неизвестного результата предыдущей команды.

### Cookie, CSRF, версии и повторные команды

| Механизм | Фактическое поведение этого снимка |
|---|---|
| Клиент | `POST /auth/verify-code` выдаёт HttpOnly `sid_client`; cookie jar отправляет её дальше |
| Банк | `POST /auth/bank-demo-login` выдаёт отдельную HttpOnly `sid_bank`, роль UNDERWRITER, уровень L2; клиентский вход сохраняется |
| Моки | Бизнес-маршруты используют `X-Api-Key`, администрирование и scenarios — `X-Admin-Key`; health/readiness открыты |
| CSRF | В `web/src/api/client.ts` есть отправка `X-CSRF-Token` из `csrf_client`/`csrf_bank`. Сервер этого снимка **не выдаёт эти cookie и не проверяет токен/Origin**; это открытый стык Q-146, не реализованная гарантия. Коллекция передаст токен, если он появился в cookie, и Origin для записывающих запросов; выдуманного токена нет |
| expectedVersion | Обязателен для банковских decision/evaluate-offer/request-info/recheck; GET карточки допускает его для признака stale. Черновик клиента PATCH использует поле **version**, а не expectedVersion |
| Idempotency-Key | Обязателен для банковских decision/request-info/recheck/outbox retry. Evaluate-offer только считает и ключа не требует. Текущие ручки create/submit/accept/sign клиента заголовок не требуют; защита повторов внутри соответствующих сервисов не равна общему middleware идемпотентности |
| Демо-управление | Только DEMO_MODE; локально код не нужен, в облачном режиме для защищённых команд нужен `X-Demo-Code`. Отдельный вход банка проверяет DEMO_MODE |

Не отправляйте sid, коды, ключи и внутренние банковские снимки в публичные логи/экспорт коллекции. Примеры предполагают локальный синтетический стенд.

## Примеры curl

Готовность и схемы (без изменения данных):

```bash
curl --fail-with-body http://127.0.0.1:8100/health/ready
curl --fail-with-body http://127.0.0.1:8100/openapi.json -o /tmp/cabinet-openapi.json
curl --fail-with-body http://127.0.0.1:8105/health/ready
```

Для следующих примеров нужен Python 3 только для чтения полей JSON. Используем API через тот же web-origin, cookie храним локально. Сначала найдём руководителя Соколовой:

```bash
API=http://localhost:8080/api
curl --fail-with-body "$API/auth/roles/001234567887" -o /tmp/cabinet-roles.json
COMPANY_ID=$(python3 -c 'import json; print(json.load(open("/tmp/cabinet-roles.json"))["company"]["id"])')
USER_ID=$(python3 -c 'import json; print(next(p["userId"] for p in json.load(open("/tmp/cabinet-roles.json"))["people"] if p["role"]=="DIRECTOR"))')
```

Получим новый код и откроем сессию. Значения кода и requestId извлекаются из ответа, а не записаны в примере:

```bash
curl --fail-with-body "$API/auth/request-code" -H 'Content-Type: application/json' \
  --data "{\"userId\":\"$USER_ID\",\"companyId\":\"$COMPANY_ID\"}" -o /tmp/cabinet-code.json
python3 -c 'import json; j=json.load(open("/tmp/cabinet-code.json")); print(json.dumps({"requestId":j["requestId"],"code":j["demoCode"]}))' > /tmp/cabinet-login.json
curl --fail-with-body -c /tmp/cabinet-cookies.txt -b /tmp/cabinet-cookies.txt \
  "$API/auth/verify-code" -H 'Content-Type: application/json' --data @/tmp/cabinet-login.json
curl --fail-with-body -b /tmp/cabinet-cookies.txt "$API/me"
```

Банк — независимая cookie в том же jar. Тело совпадает с [Bruno bank/login](collection/api/bank/login.bru):

```bash
curl --fail-with-body -c /tmp/cabinet-cookies.txt -b /tmp/cabinet-cookies.txt \
  "$API/auth/bank-demo-login" -H 'Content-Type: application/json' --data '{"role":"UNDERWRITER"}'
curl --fail-with-body -b /tmp/cabinet-cookies.txt "$API/backoffice/queue"
```

Для ручных условий используйте цепочку коллекции: карточка → evaluate-offer → decision. [Bruno evaluate](collection/api/bank/evaluate-offer.bru) и [save](collection/api/bank/save-evaluated-offer.bru) показывают контракт; их инвестиционный пример не нужно путать с оборотным сценарием README. В curl готовое тело и сохранённый ключ передаются так (файл и переменные предварительно подготовлены по ответу расчёта):

```bash
curl --fail-with-body -b /tmp/cabinet-cookies.txt \
  "$API/backoffice/applications/$APPLICATION_ID/decision" \
  -H 'Content-Type: application/json' -H "Idempotency-Key: $DECISION_ACTION_KEY" \
  --data @/tmp/cabinet-decision.json
```

Повтор персоны удаляет её демо-заявки/кредиты; используйте только перед новым прогоном. [Источник Bruno](collection/api/demo/reset-persona.bru):

```bash
curl --fail-with-body -X POST "$API/demo/personas/sokolova/reset"
```

Предпросмотр мока без сохранения — точное тело [Bruno preview-llc](collection/mocks/own-company/preview-llc.bru):

```bash
curl --fail-with-body http://127.0.0.1:8105/api/v1/scenarios/preview \
  -H 'X-Admin-Key: dev-admin-key' -H 'Content-Type: application/json' \
  --data '{"code":"jury-preview","title":"ООО: два учредителя","preset":"LLC_HEALTHY","company":{"name":"Маяк","ageMonths":24},"people":{"founders":[{"ref":"first","sharePercent":40},{"ref":"second","sharePercent":60}]}}'
```

Временные файлы с cookie/кодом удалите после проверки. Для полного пути без ручного копирования полей используйте Postman. Существующие коллекции Bruno сохранены: [API](collection/api/README.md), [моки](collection/mocks/README.md).

## Предел проверки

Структура коллекции, JSON, тела запросов и сценарии сверяются с текущим кодом и сохранённой схемой. Результат исполнения на отдельном стенде и ограничения приводятся в [отчёте проверки комплекта](../plan/reviews/C-2026-10-24-jury-package-check.md). Наличие коллекции не доказывает готовность файлов, PDF, залога, передачи подписи или всех девяти персон. Эти пути в коллекцию не включены.
