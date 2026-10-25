# API: как проверить работающий стенд

Предсдаточная сверка с main `8ff58fc5cc889f76f0ad3949a8169102310a714d` 25.10.2026. Запуск, четыре браузерных сценария и реальный генератор выписки — в [отчёте проверки](../plan/reviews/B-2026-10-25-freeze-verification.md). Исторические API-прогоны сохранены в [отчёте 24.10](../plan/reviews/C-2026-10-24-jury-final-check.md). [Назад к документации](../README.md).

## Адреса и схемы

| Сервис | Прямой локальный адрес | Сохранённая схема |
|---|---|---|
| API | http://127.0.0.1:8100 | [api.openapi.json](api.openapi.json) |
| registry | http://127.0.0.1:8101 | [mock-registry.openapi.yaml](mock-registry.openapi.yaml) |
| tax / ЕИС | http://127.0.0.1:8102 | [mock-tax.openapi.yaml](mock-tax.openapi.yaml) |
| credit-bureau | http://127.0.0.1:8103 | [mock-credit-bureau.openapi.yaml](mock-credit-bureau.openapi.yaml) |
| bank-core | http://127.0.0.1:8104 | [mock-bank-core.openapi.yaml](mock-bank-core.openapi.yaml) |
| scenarios | http://127.0.0.1:8105 | [mock-scenarios.openapi.yaml](mock-scenarios.openapi.yaml) |

У каждого сервиса `/docs` — Swagger, `/openapi.json` — текущая схема, `/health/ready` — готовность. Swagger загружает оформление с CDN; сами JSON-схемы можно читать без CDN. Файл scenarios содержит JSON, допустимый в YAML 1.2. PR #111 добавил экспорт всех шести схем: `make openapi` также обновляет TS-клиент, `make openapi-check` сверяет сохранённые схемы с кодом. Требуются uv и Node/pnpm для генерации клиента. При сверке 25.10 `make openapi` выполнен один раз: все шесть схем и TS-клиент воспроизвелись без изменений; вручную они не редактировались.

В браузере API вызывается через **http://localhost:8080/api**; nginx также принимает `/api/v1` и удаляет этот префикс. У прямого адреса `8100` маршруты идут от корня: `/applications`, а не `/api/v1/applications`. Изолированный стенд команды на **http://127.0.0.1:8090** — отдельная установка, не порт по умолчанию и не обещание его доступности на другом компьютере. Для него `apiUrl=http://127.0.0.1:8090/api`. Сохраняйте один hostname в пределах сессии: cookie от `localhost` не становится cookie для `127.0.0.1`.

## Postman v2.1

Импортируйте [postman_collection.json](postman_collection.json) через Import → File. Формат — [официальная схема v2.1](https://schema.getpostman.com/json/collection/v2.1.0/collection.json). В коллекции пять независимых папок персон: Соколова, СнабКонтракт, Станкопром, Ромашка, Гарипов с готовым файлом; отдельно — подтверждение/повтор отзыва Гарипова, проверки пяти моков, предпросмотр компании и два самостоятельных примера генератора 1С. Папка отзыва заново сбрасывает только Гарипова и удаляет его предыдущие демо-заявки/кредит. Полный путь использует реальные ручки входа, согласий, решения, предложения, подписи и кредита. Станкопром входит директором Кузнецовым, после ручного разбора банк L2 предлагает оборотные 10 млн на 12 месяцев без заданной ставки.

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
| Idempotency-Key | Обязателен для банковских decision/request-info/recheck/outbox retry, загрузки документа, подтверждения выписки и demo/bank-statement. Evaluate-offer только считает и ключа не требует. Текущие ручки create/submit/accept/sign клиента заголовок не требуют; защита повторов внутри соответствующих сервисов не равна общему middleware идемпотентности |
| Демо-управление | Только DEMO_MODE; локально код не нужен, в облачном режиме для защищённых команд нужен `X-Demo-Code`. Отдельный вход банка проверяет DEMO_MODE |

Не отправляйте sid, коды, ключи и внутренние банковские снимки в публичные логи/экспорт коллекции. Примеры предполагают локальный синтетический стенд.

## Доступ, таймлайн и отзыв

- Общая карточка/список/черновик/отправка заявки перечитывают активного пользователя и членство компании из БД. В общих маршрутах допускаются DIRECTOR и ACCOUNTANT; GUARANTOR не получает общий черновик. Чужой UUID даёт 404. Это не разрешение поручителю читать всю заявку.
- GET `/applications/{id}/timeline`: cookie клиента, без ключа идемпотентности. Ответ: applicationId, version, lastEventId, steps, checks, noteKey. lastEventId — курсор **этой заявки**, не глобальный курсор SSE. Проверки registry/taxes/creditHistory/turnover имеют waiting/running/done/delayed; steps отражают реальные события, а не угаданный маршрут по одному статусу.
- После трёх закрытых раундов новый результат NEEDS_INFO маршрутизируется в MANUAL_REVIEW. Четвёртый запрос запрещён. Подтверждённый доход может привести к обычному положительному результату даже после третьего раунда.
- POST `/applications/{id}/withdraw` с #130 требует `Content-Type: application/json` и тело `{"confirmed":true}`. Нет тела / false → 422; повтор уже завершённого отзыва → тот же WITHDRAWN. Проверено живыми запросами, включая отсутствие тела, пустое тело, false, true и повтор. Idempotency-Key в этой ручке не обязателен; повтор защищён самим сервисом.

```bash
curl --fail-with-body -b /tmp/cabinet-cookies.txt "$API/applications/$APPLICATION_ID/timeline"
# Только если действительно решили отозвать свою тестовую заявку:
curl --fail-with-body -b /tmp/cabinet-cookies.txt -H 'Content-Type: application/json' \
  -d '{"confirmed":true}' "$API/applications/$APPLICATION_ID/withdraw"
```

В папке Гарипова в Postman выберите файл `docs/test-data/garipov-statement-12-months.txt` вручную, если рабочая папка Postman отличается от корня репозитория; Newman запускайте из корня. Генератор не подменяется готовым файлом. Прогон новой версии и оставшиеся шаги описаны в отчёте.

## Документы и живые статусы

- POST `/documents`: multipart applicationId/kind/file, при запросе банка taskId; для замены replacesId. Обязателен Idempotency-Key. 1С TXT до 5 МиБ, PDF до 10 МиБ/30 страниц; содержимое проверяется независимо от имени. Это границы кода, не результат повторного отрицательного прогона всех ошибок.
- GET `/documents?applicationId=...`, GET `/documents/{id}`, GET `/documents/{id}/download`. Клиент читает свою компанию; банк явно передаёт `?zone=bank`, PDF для просмотра — дополнительно `preview=true`. Без zone=bank выбирается клиентская сессия.
- Разбор — PENDING/PROCESSING → PARSED или FAILED. POST `/documents/{id}/confirm` принимает sha256, acknowledged=true и массив months с month/businessIncomingKopecks. Полные месяцы и допустимые суммы берутся из ответа разбора, не выдумываются; нужны Idempotency-Key и явная проверка пользователем. Пример тела — [интеграционный тест](../../api/tests/integration/test_statement_source.py). PARSED не означает подтверждение дохода.
- Новые GET `/contracts/{id}/document` отдают сохранённый PDF с X-Content-SHA256; старые JSON совместимы. Коллекция проверяет Content-Type, сигнатуру PDF и наличие хеша; отдельно проверены фактические SHA-256 трёх файлов.
- GET `/events/stream?zone=client|bank`: cookie соответствующей зоны, text/event-stream, восстановление по Last-Event-ID или lastEventId. Проверены вход, replay/resync и 401 без сессии; длительный/нагрузочный прогон не выполнялся.
- POST `/demo/bank-statement` работает: клиентская сессия, `Idempotency-Key`, JSON с `applicationId` и `taskId` открытой документной задачи своей компании; ответ 201 — метаданные сохранённого документа с `origin=DEMO_GENERATED`. Это не ответ с байтами файла. Дальше действуют обычные фоновый разбор и отдельное подтверждение поступлений. 25.10 проверен путь Гарипова от генерации до выдачи: 30 запросов / 51 проверка / 0 ошибок. [Готовый независимый файл](../test-data/README.md) остаётся способом отдельно проверить загрузку.


### Генератор выписки 1С

Сервис scenarios возвращает файл по `GET /api/v1/scenarios/{code}/documents/bank-statement?months=12` и `POST /api/v1/documents/bank-statement`. Оба маршрута требуют `X-Admin-Key`. `months` — 1–24; для источника дохода кабинет принимает не меньше трёх полных месяцев. Файл Windows-1251, строки CRLF, заголовки `Content-Disposition: attachment` и `X-Mock-Simulated: true`. При одинаковых параметрах и дате GET возвращает одинаковые байты. Все данные — симуляция.

```bash
export MOCK_ADMIN_KEY=dev-admin-key # только локальный стенд; для другого используйте его ключ
curl --fail-with-body -H "X-Admin-Key: ${MOCK_ADMIN_KEY}" \
  'http://127.0.0.1:8105/api/v1/scenarios/garipov/documents/bank-statement?months=12' \
  -o /tmp/garipov-statement.txt
curl --fail-with-body -H "X-Admin-Key: ${MOCK_ADMIN_KEY}" -H 'Content-Type: application/json' \
  -d '{"inn":"001298765490","months":12,"avgMonthlyRevenueRub":700000,"netMarginPercent":14.2857,"minMonthlySurplusRub":100000,"seed":130}' \
  'http://127.0.0.1:8105/api/v1/documents/bank-statement' -o /tmp/custom-statement.txt
```

При `APP_TODAY=2026-10-21` Гарипов получает октябрь 2025 — сентябрь 2026: ежемесячно 700000 ₽ входящих / 600000 ₽ исходящих, остаток 0 → 1200000 ₽. Настоящий парсер подтверждает суммы, но оставляет `UNCLASSIFIED_RECEIPTS`: бизнес-происхождение денег подтверждает клиент. Папка Postman «Генератор выписки 1С: примеры» не создаёт заявку и не отправляет ответы за клиента.

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

Структура коллекции, JSON, тела запросов и сценарии сверяются с текущим кодом и сохранённой схемой. Результат исполнения на отдельном стенде и ограничения приводятся в [окончательном отчёте проверки комплекта](../plan/reviews/C-2026-10-24-jury-final-check.md). Три новых PDF проверены в положительных путях; у Ромашки отказ и договора нет. Гарипов с готовым файлом включён в окончательную коллекцию и проверен до выдачи; его multipart-файл и происхождение описаны в docs/test-data. Полный набор ошибок/замены, залог, передача подписи, все девять персон, Postman GUI и новый браузерный прогон этой проверкой не подтверждаются.
