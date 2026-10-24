# Документация проекта

Начните с [README: запуск и самопроверка](../README.md). Данные синтетические, кредитные решения детерминированные. Этот навигатор отделяет описание текущей реализации от истории проектирования; история и доказательства сохранены по прежним адресам.

## Комплект для жюри

| Что нужно | Где открыть |
|---|---|
| Назначение, запуск, настройки и четыре основных сценария | [README](../README.md) |
| Архитектура реально поднимаемого стенда | [Архитектура](architecture/architecture.md) |
| Статусы и переходы заявки | [Машина состояний](architecture/state_machine.md) |
| Таблицы и связи PostgreSQL | [Модель данных](architecture/data_model.md) |
| API, Swagger, cookie-сессии, примеры curl | [Навигатор API](api/README.md) |
| Коллекция запросов Postman v2.1 | [postman_collection.json](api/postman_collection.json) |
| Существующие запросы Bruno | [API](api/collection/api/README.md), [моки](api/collection/mocks/README.md) |
| Сценарии и пределы проверки | [Каталог сценариев](test-scenarios.md) |
| Сторонние компоненты, лицензии и пять моков | [THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md), [полный реестр](../licenses/README.md) |
| Проверка требований сдачи | [Чек-лист](plan/80-delivery/05-submission-checklist.md) |

- [Короткий показ жюри](jury-demo-script.md) и [финальная сверка / продолжение](plan/reviews/C-2026-10-24-jury-final-check.md).

## Требования и принятые решения

- [Текст кейса](case.md) и [уточнения организаторов](plan/10-product/00-organizer-clarifications.md).
- [Требования](plan/10-product/01-requirements-matrix.md), [персоны](plan/10-product/02-personas.md), [оракул с ожидаемыми числами](plan/30-decisioning/17-persona-walkthrough.md).
- [Кредитный конвейер](plan/30-decisioning/01-pipeline-overview.md), [формулы платежей](plan/30-decisioning/16-loan-math.md), [экономические источники и допущения](plan/30-decisioning/18-economic-assumptions.md).
- [Спецификация моков](specs/mocks.md) и [руководство по ним](mocks-guide.md).
- [Реестр принятых решений](plan/00-meta/05-decisions-index.md), [открытые вопросы](plan/00-meta/06-open-questions.md).

<details>
<summary>План, история и доказательства проверок</summary>

Эти материалы содержат как реализованные, так и будущие функции. Статус карточки не заменяет проверку кода и стенда. Используйте README и страницы архитектуры для описания текущей поставки.

- [Весь план](plan/README.md), [карта документов](plan/00-meta/04-planning-backlog.md), [реестр задач](plan/80-delivery/01-work-breakdown.md).
- [Передача работы](plan/00-meta/08-handoff.md), [журнал](plan/00-meta/07-journal.md), [протокол агентов](plan/00-meta/03-collaboration-protocol.md).
- [Актуализация комплекта 24.10](plan/reviews/C-2026-10-24-jury-package-refresh.md) и [первый прогон](plan/reviews/C-2026-10-24-jury-package-check.md).
- [Аудит 23.10](plan/reviews/B-2026-10-23-delivery-audit.md), [передача банка 23.10](plan/reviews/B-2026-10-23-bank-handoff.md).
- [Стратегия тестирования](plan/70-quality/01-test-strategy.md), [браузерные проверки и API](plan/70-quality/05-integration-and-e2e.md).
- [Проектный сценарий жюри](plan/80-delivery/07-jury-self-check.md): полный целевой путь; фактические шаги и ограничения — в корневом README.

</details>
