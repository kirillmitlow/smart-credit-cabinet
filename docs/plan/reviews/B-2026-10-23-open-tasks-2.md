# Реестр незакрытых карточек на 23.10.2026 — часть 2

| | |
|---|---|
| Статус | REVIEW |
| Владелец | Агент B |
| База | main `4e4d186`, исходные статусы до отметки B о начале T-362 |

Приложение к [аудиту](B-2026-10-23-delivery-audit.md). REVIEW означает ожидание приёмки. Часы — исходная оценка всей карточки, **не измеренный остаток**; статусы частично запаздывают. Всего 159 карточек, включая 27 REVIEW. M — Must, S — Should, C — Could.

| Задача | Приоритет | Статус | Исходные часы |
|---|---|---|---:|
| [T-402: Подключить orval и общий слой запросов: ошибки, ключи идемпотентности](../80-delivery/tasks/T-402-web-api-layer-orval.md) | M | REVIEW | 5 |
| [T-403: Настроить роутинг, зоны клиента/банка/демо и защиту маршрутов](../80-delivery/tasks/T-403-web-routing-zones-guards.md) | M | REVIEW | 5 |
| [T-404: Сделать оболочку: шапка, постоянная демо-плашка, цветовая полоса зоны банка](../80-delivery/tasks/T-404-web-shell-demo-badge.md) | M | REVIEW | 4 |
| [T-405: Завести словарь текстов и форматтеры денег, дат, процентов](../80-delivery/tasks/T-405-web-texts-dictionary-infra.md) | M | REVIEW | 4 |
| [T-406: Подготовить тестовую обвязку фронта: Vitest, MSW, axe, мок EventSource](../80-delivery/tasks/T-406-web-test-infra.md) | M | REVIEW | 4 |
| [T-407: Написать хук `useEventStream`: SSE, докачка, запасной опрос](../80-delivery/tasks/T-407-web-use-event-stream.md) | M | REVIEW | 5 |
| [T-408: Сделать вход, шаги 1–2: ИНН, выбор пользователя компании, личный ИНН](../80-delivery/tasks/T-408-web-login-inn.md) | M | REVIEW | 5 |
| [T-409: Сделать вход, шаги 3–4: одноразовый код и выбор компании](../80-delivery/tasks/T-409-web-login-code-company.md) | M | REVIEW | 3 |
| [T-410: Сделать главную: «Что нужно от вас», мои заявки, кредиты, «Нужны деньги»](../80-delivery/tasks/T-410-web-home.md) | M | REVIEW | 5 |
| [T-411: Добавить на главную блок предодобрения «Вам доступно до …»](../80-delivery/tasks/T-411-web-home-preapproval.md) | S | TODO | 2 |
| [T-414: Добавить в мастер поле «Опишите своими словами» с подсказками](../80-delivery/tasks/T-414-web-wizard-free-text.md) | S | TODO | 5 |
| [T-415: Сделать каталог продуктов и калькулятор платежа](../80-delivery/tasks/T-415-web-catalog-calculator.md) | M | TODO | 4 |
| [T-416: Сделать заявку по шагам: каркас, автосохранение, шаги «Условия» и «Проверьте и отправьте»](../80-delivery/tasks/T-416-web-application-stepper.md) | M | REVIEW | 6 |
| [T-418: Шаг заявки «Что нужно для продукта»: контракт, залог, поручитель](../80-delivery/tasks/T-418-web-application-product-step.md) | M | TODO | 4 |
| [T-419: Шаг заявки «Согласия»: отдельные галочки и один код на пакет](../80-delivery/tasks/T-419-web-application-consents-step.md) | M | REVIEW | 6 |
| [T-420: Добавить «Передать руководителю» и отзыв согласия с предупреждением](../80-delivery/tasks/T-420-web-handover-and-consent-revoke.md) | M | TODO | 3 |
| [T-421: Сделать страницу заявки с таймлайном и выбором блока исхода](../80-delivery/tasks/T-421-web-application-page-timeline.md) | M | REVIEW | 6 |
| [T-423: Сделать блок исхода «Три карточки» и «Как получить то, что просили»](../80-delivery/tasks/T-423-web-outcome-counter-offer.md) | M | PARTIAL | 6 |
| [T-424: Сделать блок «Нужна информация» и экран «Что нужно от вас»: загрузка выписки](../80-delivery/tasks/T-424-web-outcome-needs-info-tasks.md) | M | PARTIAL | 6 |
| [T-425: Сделать блок «Ручное рассмотрение» и действия поручителя](../80-delivery/tasks/T-425-web-outcome-manual-guarantor.md) | M | TODO | 4 |
| [T-426: Сделать принятие предложения и экран подписания с прогрессом выдачи](../80-delivery/tasks/T-426-web-accept-and-sign.md) | M | PARTIAL | 6 |
| [T-428: Сделать колокольчик, тосты и страницу уведомлений](../80-delivery/tasks/T-428-web-notifications-ui.md) | M | TODO | 5 |
| [T-429: Сделать зону банка: очередь ручного рассмотрения](../80-delivery/tasks/T-429-web-bank-queue.md) | M | REVIEW | 5 |
| [T-430: Сделать карточку заявки андеррайтера: каркас и блоки данных](../80-delivery/tasks/T-430-web-bank-card.md) | M | REVIEW | 6 |
| [T-431: Блоки карточки банка: платёж и устойчивость, ставка, источники, встречные](../80-delivery/tasks/T-431-web-bank-card-money-sources.md) | M | REVIEW | 4 |
| [T-432: Сделать действия андеррайтера: одобрить, запросить информацию, отказать, перезапросить](../80-delivery/tasks/T-432-web-bank-actions.md) | M | TODO | 6 |
| [T-433: Добавить ручной режим встречного: ввод варианта и пересчёт](../80-delivery/tasks/T-433-web-bank-manual-offer.md) | S | TODO | 6 |
| [T-434: Сделать демо-панель: страница `/demo`, выдвижной язычок, шпаргалка персон](../80-delivery/tasks/T-434-web-demo-panel-base.md) | M | REVIEW | 5 |
| [T-435: Демо-панель: сброс стенда и персоны, сбои моков, полоса активного сбоя](../80-delivery/tasks/T-435-web-demo-reset-chaos.md) | M | REVIEW | 5 |
| [T-437: Заполнить словарь текстов по 60-06 и покрыть тестами](../80-delivery/tasks/T-437-web-texts-full-60-06.md) | M | TODO | 5 |
| [T-438: Пройти доступность и состояния всех экранов: клавиатура, фокус, масштаб 200%](../80-delivery/tasks/T-438-web-accessibility-sweep.md) | S | TODO | 4 |
| [T-441: Написать e2e: СнабКонтракт, Ромашка, Вектор, Орлов](../80-delivery/tasks/T-441-e2e-counter-reject-notelig.md) | M | TODO | 5 |
| [T-442: Написать e2e: СтанкоПром с двумя пользователями и рабочим местом банка](../80-delivery/tasks/T-442-e2e-stankoprom-bank.md) | M | TODO | 6 |
| [T-443: Написать e2e: Гарипов — выписка, открытие счёта, выдача](../80-delivery/tasks/T-443-e2e-garipov.md) | M | TODO | 4 |
| [T-444: Написать e2e: Заря и Быстрый старт](../80-delivery/tasks/T-444-e2e-zarya-quickstart.md) | M | TODO | 5 |
| [T-445: Написать e2e: живые статусы, демо-панель и устойчивость к сбоям](../80-delivery/tasks/T-445-e2e-live-demo-resilience.md) | S | TODO | 5 |
| [T-505: Написать .env.example и проверку соответствия настройкам и compose](../80-delivery/tasks/T-505-env-example.md) | M | IN_PROGRESS | 3 |
| [T-506: Добавить сервис nlu и режим профиля ai в compose](../80-delivery/tasks/T-506-compose-ai-profile.md) | S | TODO | 2 |
| [T-507: Написать docker-compose.cloud.yml с HTTPS и закрытыми портами](../80-delivery/tasks/T-507-compose-cloud.md) | S | TODO | 4 |
| [T-508: Добавить профиль obs: Prometheus и Grafana](../80-delivery/tasks/T-508-compose-obs-profile.md) | C | TODO | 4 |
| [T-511: Подключить в CI проверки контрактов, безопасности и THIRD_PARTY_NOTICES](../80-delivery/tasks/T-511-ci-contracts-security-notices.md) | M | TODO | 5 |
| [T-512: Собрать CI-задание e2e: compose, smoke, Bruno, персоны, контракты, Schemathesis, Playwright 🧠](../80-delivery/tasks/T-512-ci-e2e.md) | M | TODO | 6 |
| [T-513: Настроить ночной и полный прогон: синтетика, хаос, нагрузка](../80-delivery/tasks/T-513-ci-nightly-full.md) | S | TODO | 4 |
| [T-514: Настроить публикацию образов в GHCR по тегу submission](../80-delivery/tasks/T-514-ci-release-ghcr.md) | M | TODO | 5 |
| [T-515: Написать scripts/smoke.sh и ожидание готовности стенда](../80-delivery/tasks/T-515-smoke-script.md) | M | TODO | 3 |
| [T-516: Собрать обвязку Testcontainers для интеграционных тестов](../80-delivery/tasks/T-516-testcontainers-harness.md) | M | TODO | 4 |
| [T-517: Собрать обвязку персон по API: сброс, ожидание, ожидаемые исходы](../80-delivery/tasks/T-517-personas-api-harness.md) | M | PARTIAL | 4 |
| [T-518: Собрать обвязку Playwright: конфигурация, фикстуры, axe, трассы](../80-delivery/tasks/T-518-playwright-harness.md) | M | PARTIAL | 5 |
| [T-519: Настроить фаззинг API Schemathesis для api и моков](../80-delivery/tasks/T-519-schemathesis-harness.md) | S | TODO | 3 |
| [T-520: Собрать нагрузочный сценарий Locust с проверкой корректности](../80-delivery/tasks/T-520-locust-harness.md) | S | TODO | 5 |
| [T-521: Публиковать отчёт синтетики в CI и в таблицу качества README](../80-delivery/tasks/T-521-synthetic-report-ci.md) | S | TODO | 3 |
| [T-522: Написать check-docs: ссылки, шапки и mermaid в документах плана](../80-delivery/tasks/T-522-check-docs-links.md) | M | TODO | 3 |
| [T-523: Добавить в check-docs сверку каталога TS-NNN и меток автотестов](../80-delivery/tasks/T-523-check-docs-ts-labels.md) | M | TODO | 3 |
| [T-524: Сделать генерацию THIRD_PARTY_NOTICES из lock-файлов с ручным разделом](../80-delivery/tasks/T-524-third-party-notices.md) | M | TODO | 5 |
| [T-525: Написать выгрузку диаграмм mermaid в SVG/PNG и сделать архитектурную схему для сдачи](../80-delivery/tasks/T-525-diagram-export-architecture.md) | M | TODO | 3 |
| [T-526: Построить диаграмму состояний заявки из кода и тест «диаграмма = таблица»](../80-delivery/tasks/T-526-diagram-states.md) | M | TODO | 4 |
| [T-527: Построить ER-диаграмму модели данных из метаданных и миграций](../80-delivery/tasks/T-527-diagram-er.md) | M | TODO | 4 |
| [T-528: Превратить каталог тестовых сценариев 70-09 в артефакт сдачи docs/test-scenarios.md](../80-delivery/tasks/T-528-test-scenarios-catalog.md) | M | TODO | 4 |
| [T-529: Сгенерировать папку docs/adr из реестра решений](../80-delivery/tasks/T-529-adr-folder.md) | S | TODO | 4 |
| [T-530: Написать статические разделы README по плану 80-06](../80-delivery/tasks/T-530-readme-static.md) | M | TODO | 5 |
| [T-531: Автоматизировать генерируемые части README: переменные, порты, ИНН персон, таблица качества](../80-delivery/tasks/T-531-readme-generated.md) | M | TODO | 4 |
| [T-532: Встроить сценарий самопроверки жюри в README и привязать к интерфейсу](../80-delivery/tasks/T-532-jury-self-check-readme.md) | M | TODO | 4 |
| [T-533: Провести репетицию самопроверки жюри на свежем клонировании](../80-delivery/tasks/T-533-jury-rehearsal.md) | M | TODO | 3 |
| [T-534: Измерить память, время сборки и запуска и записать цифры в README](../80-delivery/tasks/T-534-resource-measurement.md) | M | TODO | 2 |
| [T-535: Проверить запуск на чистой Linux-машине без кэша и без интернета после сборки](../80-delivery/tasks/T-535-clean-machine-linux.md) | M | TODO | 4 |
| [T-536: Подготовить пакет проверки на Windows для команды](../80-delivery/tasks/T-536-windows-check-pack.md) | M | TODO | 3 |
| [T-537: Подготовить пакет юзабилити-теста для команды](../80-delivery/tasks/T-537-usability-pack.md) | S | TODO | 2 |
| [T-538: Подготовить репозиторий к сдаче: доступ, чистка, фиксация версии](../80-delivery/tasks/T-538-repo-prep-submission.md) | M | TODO | 3 |
| [T-539: Выпустить версию: тег submission, публикация образов, финальная проверка pull](../80-delivery/tasks/T-539-release-and-tag.md) | M | TODO | 3 |
| [T-540: Развернуть облачный стенд на VPS и прогнать smoke](../80-delivery/tasks/T-540-cloud-stand.md) | S | BLOCKED | 6 |
| [T-541: Проверить и закрепить выбор image/build в compose](../80-delivery/tasks/T-541-image-build-policy.md) | M | TODO | 3 |
| [T-542: Провести регрессионный проход перед заморозкой и собрать список известных проблем](../80-delivery/tasks/T-542-freeze-regression.md) | M | TODO | 3 |
| [T-543: Сделать make openapi: выгрузка всех шести схем и клиента TypeScript](../80-delivery/tasks/T-543-make-openapi-all.md) | M | TODO | 3 |
| [T-544: Собрать коллекцию Bruno для api: самопроверка по персонам](../80-delivery/tasks/T-544-bruno-collection-api.md) | M | TODO | 5 |
