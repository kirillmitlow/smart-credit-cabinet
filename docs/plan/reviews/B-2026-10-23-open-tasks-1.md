# Реестр незакрытых карточек на 23.10.2026 — часть 1

| | |
|---|---|
| Статус | REVIEW |
| Владелец | Агент B |
| База | main `4e4d186`, исходные статусы до отметки B о начале T-362 |

Приложение к [аудиту](B-2026-10-23-delivery-audit.md). REVIEW означает ожидание приёмки. Часы — исходная оценка всей карточки, **не измеренный остаток**; статусы частично запаздывают. Всего 159 карточек, включая 27 REVIEW. M — Must, S — Should, C — Could.

| Задача | Приоритет | Статус | Исходные часы |
|---|---|---|---:|
| [T-129: Реализовать досинхронизацию, ежемесячное переприменение, фоновые повторы и сброс 🧠](../80-delivery/tasks/T-129-mocks-resync-reset.md) | M | PARTIAL | 6 |
| [T-130: Реализовать генератор выписки из другого банка в формате 1С](../80-delivery/tasks/T-130-mocks-bank-statement-1c.md) | S | TODO | 5 |
| [T-134: Записать персоны garipov и quick-start](../80-delivery/tasks/T-134-mocks-personas-garipov-quickstart.md) | M | PARTIAL | 4 |
| [T-135: Записать десять технических сценариев t-*](../80-delivery/tasks/T-135-mocks-technical-scenarios.md) | M | TODO | 5 |
| [T-136: Написать сквозные тесты моков: персоны, эндпоинты, ошибки, ключи](../80-delivery/tasks/T-136-mocks-tests-endpoints.md) | M | TODO | 4 |
| [T-137: Написать сквозные тесты БКИ и АБС: арифметика, согласия, выдача, идемпотентность](../80-delivery/tasks/T-137-mocks-tests-bki-bank.md) | M | TODO | 5 |
| [T-138: Написать сквозные тесты моков: chaos, «сегодня», синхронизация, согласованность, сброс](../80-delivery/tasks/T-138-mocks-tests-chaos-sync.md) | M | TODO | 5 |
| [T-139: Выгрузить OpenAPI моков и добавить контрактный тест](../80-delivery/tasks/T-139-mocks-openapi-export.md) | M | TODO | 4 |
| [T-140: Собрать коллекцию Bruno для моков](../80-delivery/tasks/T-140-mocks-bruno-collection.md) | M | TODO | 5 |
| [T-141: Сверить встроенные персоны с оракулом 30-17 и прогоном ядра (Q-020)](../80-delivery/tasks/T-141-mocks-persona-numbers-check.md) | M | TODO | 4 |
| [T-203: Реализовать идемпотентность `POST` по `Idempotency-Key`](../80-delivery/tasks/T-203-idempotency-keys.md) | M | TODO | 4 |
| [T-206: Настроить OpenAPI как контракт: `operationId`, теги, выгрузка в `docs/api`](../80-delivery/tasks/T-206-openapi-contract.md) | M | TODO | 3 |
| [T-207: Добавить лимит частоты, CSRF-токен и заголовки безопасности](../80-delivery/tasks/T-207-rate-limit-csrf-headers.md) | M | TODO | 4 |
| [T-214: Покрыть тестами матрицу прав и защиту всех маршрутов](../80-delivery/tasks/T-214-rbac-matrix-tests.md) | M | TODO | 4 |
| [T-222: Добавить участника-поручителя и ограниченный доступ к его действиям](../80-delivery/tasks/T-222-guarantor-participant.md) | M | TODO | 5 |
| [T-223: Ввести полномочия доверенности и приостановку сотрудника](../80-delivery/tasks/T-223-poa-permissions.md) | M | TODO | 3 |
| [T-231: Реализовать предохранитель в Redis по окну времени](../80-delivery/tasks/T-231-circuit-breaker.md) | M | TODO | 5 |
| [T-236: Написать адаптер АБС на запись: открытие счёта и выдача](../80-delivery/tasks/T-236-adapter-bank-core-write.md) | M | REVIEW | 3 |
| [T-237: Разделить `FreshGateway` и `CachedGateway`: кэш только для автозаполнения](../80-delivery/tasks/T-237-cached-vs-fresh-gateway.md) | M | TODO | 3 |
| [T-238: Покрыть адаптеры контрактными тестами и режимами сбоев моков](../80-delivery/tasks/T-238-adapter-contract-and-chaos-tests.md) | M | TODO | 5 |
| [T-243: Добавить режим PREVIEW и предодобренное предложение на главной](../80-delivery/tasks/T-243-preview-and-preapproval.md) | S | TODO | 5 |
| [T-244: Написать парсер суммы из текста без ИИ](../80-delivery/tasks/T-244-amount-parser.md) | S | TODO | 4 |
| [T-245: Подключить клиент `nlu` и `POST /wizard/parse-text` с подсказками](../80-delivery/tasks/T-245-wizard-parse-text.md) | S | TODO | 5 |
| [T-255: Сделать `GET …/timeline`: проекция событий в шесть шагов клиента](../80-delivery/tasks/T-255-application-timeline.md) | M | TODO | 4 |
| [T-256: Реализовать отзыв заявки и закрытие связанных задач](../80-delivery/tasks/T-256-application-withdraw.md) | M | TODO | 3 |
| [T-257: Добавить залог и поручительство в заявку и возврат в проверку](../80-delivery/tasks/T-257-collateral-guarantor-in-application.md) | M | TODO | 4 |
| [T-258: Сделать таймер истечения сроков (по умолчанию выключен)](../80-delivery/tasks/T-258-expiry-timer.md) | S | TODO | 3 |
| [T-262: Реализовать отзыв согласия и остановку новых запросов](../80-delivery/tasks/T-262-consent-revocation.md) | M | TODO | 3 |
| [T-264: Добавить «Передать руководителю» и гейт отправки по согласиям](../80-delivery/tasks/T-264-handover-to-director.md) | M | TODO | 3 |
| [T-271: Сделать сторож зависших запусков, аренду и `PIPELINE_ERROR`](../80-delivery/tasks/T-271-pipeline-reaper-lease.md) | M | TODO | 5 |
| [T-276: Добавить воспроизведение решения и «золотые» решения персон](../80-delivery/tasks/T-276-decision-replay-golden.md) | S | TODO | 4 |
| [T-277: Реализовать повторные прогоны: ответ клиента и перепроверка источников](../80-delivery/tasks/T-277-pipeline-rerun-flows.md) | M | PARTIAL | 4 |
| [T-278: Реализовать outbox и ретранслятор «толчок + страховка»](../80-delivery/tasks/T-278-outbox-relay.md) | M | REVIEW | 6 |
| [T-279: Подключить обработчики сообщений в БКИ: регистрация, решение, отзыв, обязательство](../80-delivery/tasks/T-279-outbox-bureau-handlers.md) | M | TODO | 4 |
| [T-283: Добавить платежи для продукта под контракт, линии и овердрафта](../80-delivery/tasks/T-283-money-bullet-line-overdraft.md) | M | TODO | 4 |
| [T-284: Добавить эффективную ставку и расчёт досрочного погашения](../80-delivery/tasks/T-284-money-eir-prepayment.md) | C | TODO | 3 |
| [T-299: Добавить вклад факторов и блок «что изменить, чтобы одобрили»](../80-delivery/tasks/T-299-explanations-factors-whatif.md) | M | TODO | 4 |
| [T-302: Написать фикстуры остальных персон и технических сценариев](../80-delivery/tasks/T-302-core-fixtures-all-personas.md) | M | TODO | 5 |
| [T-303: Покрыть ядро property-тестами инвариантов INV-01…INV-53](../80-delivery/tasks/T-303-core-property-tests.md) | M | TODO | 6 |
| [T-310: Сделать детерминированный генератор случайных чисел и популяцию компаний](../80-delivery/tasks/T-310-simulator-rng-population.md) | S | TODO | 4 |
| [T-311: Реализовать помесячный движок денежного потока бизнеса и правило дефолта](../80-delivery/tasks/T-311-simulator-engine.md) | S | TODO | 6 |
| [T-312: Добавить в движок виды кредитов: под контракт, линию и овердрафт](../80-delivery/tasks/T-312-simulator-loan-kinds.md) | S | TODO | 4 |
| [T-313: Сформировать наблюдаемые признаки «как из моков» и предысторию 24 месяца](../80-delivery/tasks/T-313-simulator-observables.md) | S | TODO | 5 |
| [T-314: Реализовать вероятностный стресс-тест одной заявки (Монте-Карло)](../80-delivery/tasks/T-314-stress-test-probabilistic.md) | S | TODO | 5 |
| [T-315: Подключить вероятностный стресс к конвейеру и правилам лимитов](../80-delivery/tasks/T-315-stress-pipeline-integration.md) | S | TODO | 4 |
| [T-316: Построить синтетический портфель и откалибровать долю дефолтов ~6%](../80-delivery/tasks/T-316-simulator-portfolio-calibration.md) | S | TODO | 5 |
| [T-317: Реализовать метрики качества скоркарты: AUC, Gini, KS, PSI, калибровка](../80-delivery/tasks/T-317-validation-metrics.md) | S | TODO | 5 |
| [T-318: Собрать отчёт валидации: `make validation-report`, Markdown, JSON, графики](../80-delivery/tasks/T-318-validation-report-build.md) | S | TODO | 5 |
| [T-319: Пересчитать баллы скоркарты логистической регрессией с WoE](../80-delivery/tasks/T-319-scorecard-recalibration.md) | C | TODO | 6 |
| [T-320: Добавить массовые тесты на синтетической популяции](../80-delivery/tasks/T-320-synthetic-population-tests.md) | S | TODO | 5 |
| [T-321: Отдать отчёт валидации в зону банка для страницы «Качество модели»](../80-delivery/tasks/T-321-model-quality-endpoint.md) | C | TODO | 3 |
| [T-330: Написать парсер выписки 1С как чистую функцию](../80-delivery/tasks/T-330-parser-1c-statement.md) | M | TODO | 6 |
| [T-331: Собрать корпус и тесты парсера выписки 1С](../80-delivery/tasks/T-331-parser-1c-corpus-tests.md) | M | TODO | 4 |
| [T-332: Реализовать `FileStore` в Postgres, загрузку и скачивание документов](../80-delivery/tasks/T-332-filestore-upload-download.md) | M | TODO | 6 |
| [T-333: Запустить разбор выписки фоновой задачей и вернуть ошибки в задачу клиента](../80-delivery/tasks/T-333-statement-parse-task.md) | M | TODO | 4 |
| [T-334: Использовать разобранную выписку в снимках и признаках выручки](../80-delivery/tasks/T-334-statement-to-facts.md) | M | TODO | 3 |
| [T-335: Дать андеррайтеру просмотр PDF-документов клиента](../80-delivery/tasks/T-335-pdf-view-by-underwriter.md) | M | TODO | 3 |
| [T-336: Генерировать договор, график и заявление в PDF через WeasyPrint](../80-delivery/tasks/T-336-pdf-generation-weasyprint.md) | M | TODO | 6 |
| [T-337: Извлекать кандидатов цифр отчётности из текстовых PDF с подтверждением](../80-delivery/tasks/T-337-pdf-candidates-extraction.md) | C | TODO | 5 |
| [T-342: Реализовать выдачу: открытие счёта, выдача в АБС, кредит и график](../80-delivery/tasks/T-342-disbursement-workflow.md) | M | REVIEW | 5 |
| [T-343: Доказать выдачу «ровно один раз»: потеря ответа и параллельные подписи](../80-delivery/tasks/T-343-disbursement-exactly-once.md) | M | REVIEW | 5 |
| [T-344: Реализовать «Мои кредиты»: кредит, график, ближайший платёж](../80-delivery/tasks/T-344-loans-schedule-api.md) | M | REVIEW | 5 |
| [T-350: Создавать задачи клиенту: шаблоны, запрос от конвейера и андеррайтера](../80-delivery/tasks/T-350-client-tasks-create.md) | M | PARTIAL | 4 |
| [T-351: Принять ответы раундом и вернуть заявку в проверку](../80-delivery/tasks/T-351-client-tasks-answer-round.md) | M | PARTIAL | 5 |
| [T-352: Реализовать SSE `/events/stream` с докачкой из журнала](../80-delivery/tasks/T-352-sse-event-stream.md) | M | TODO | 6 |
| [T-354: Реализовать уведомления клиента: правила, колокольчик, прочтение](../80-delivery/tasks/T-354-notifications-client.md) | M | TODO | 5 |
| [T-355: Реализовать уведомления зоны банка и счётчик колокольчика](../80-delivery/tasks/T-355-notifications-bank.md) | M | TODO | 3 |
| [T-360: Реализовать очередь ручного рассмотрения `GET /backoffice/queue`](../80-delivery/tasks/T-360-backoffice-queue.md) | M | REVIEW | 4 |
| [T-361: Собрать карточку заявки для андеррайтера](../80-delivery/tasks/T-361-backoffice-card.md) | M | REVIEW | 5 |
| [T-362: Реализовать решение андеррайтера: одобрить, встречное, отказать, причина и уровни](../80-delivery/tasks/T-362-backoffice-decision.md) | M | TODO | 6 |
| [T-363: Добавить запрос информации и перепроверку источников](../80-delivery/tasks/T-363-backoffice-request-info-recheck.md) | M | TODO | 4 |
| [T-364: Дать андеррайтеру ручной расчёт варианта: `evaluate-offer` и сохранение](../80-delivery/tasks/T-364-backoffice-manual-offer.md) | S | TODO | 6 |
| [T-373: Сгенерировать тестовую выписку в демо-режиме](../80-delivery/tasks/T-373-demo-bank-statement.md) | M | TODO | 3 |
| [T-374: Защитить сброс и сбои кодом стенда в облаке](../80-delivery/tasks/T-374-demo-stand-code.md) | S | REVIEW | 2 |
| [T-375: Сделать песочницу правил «а что если»](../80-delivery/tasks/T-375-rules-sandbox-what-if.md) | C | TODO | 5 |
| [T-380: Написать сервис `nlu`: USER2-base + kNN, `POST /v1/parse`](../80-delivery/tasks/T-380-nlu-service.md) | S | TODO | 6 |
| [T-381: Упаковать `nlu`: веса с Hugging Face, хеш, профиль `ai`, замеры](../80-delivery/tasks/T-381-nlu-packaging.md) | S | TODO | 5 |
| [T-382: Расширить набор фраз до ≥ 120 и замерить качество на нашем интерфейсе](../80-delivery/tasks/T-382-nlu-evaluation-set.md) | C | TODO | 4 |
| [T-390: Выдать метрики Prometheus из таблиц Postgres и Redis](../80-delivery/tasks/T-390-metrics-prometheus.md) | S | TODO | 5 |
| [T-392: Прогнать все персоны и технические сценарии по API](../80-delivery/tasks/T-392-api-persona-tests.md) | M | TODO | 6 |
| [T-393: Написать критические контрактные тесты `api` и фикстуры для Schemathesis](../80-delivery/tasks/T-393-api-contract-tests-critical.md) | M | TODO | 5 |
| [T-394: Покрыть конвейер сценариями сбоев: рестарты, потеря Redis, падение БКИ](../80-delivery/tasks/T-394-resilience-chaos-tests.md) | M | TODO | 6 |
| [T-395: Добавить цепочку хешей аудита и проверку целостности](../80-delivery/tasks/T-395-audit-hash-chain.md) | C | TODO | 3 |
| [T-400: Создать каркас `web`: Vite, React 19, TypeScript strict, Mantine](../80-delivery/tasks/T-400-web-skeleton.md) | M | REVIEW | 5 |
| [T-401: Собрать образ `web`: Dockerfile и `nginx.conf` с прокси `/api` и SSE](../80-delivery/tasks/T-401-web-dockerfile-nginx.md) | M | REVIEW | 3 |
