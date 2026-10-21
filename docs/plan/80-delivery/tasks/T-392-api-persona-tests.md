# T-392. Прогнать все персоны и технические сценарии по API

| | |
|---|---|
| Статус | TODO |
| Владелец | не назначен (Claude Code или Codex, по очереди смен) |
| Ветка | `feat/api-persona-tests` |
| Оценка | ~6 ч |
| Приоритет | M (Must) |
| Тонкий сквозной сценарий | нет |
| Зависит от | [T-391](T-391-api-e2e-sokolova-thin.md), [T-302](T-302-core-fixtures-all-personas.md), [T-351](T-351-client-tasks-answer-round.md), [T-362](T-362-backoffice-decision.md), [T-263](T-263-contract-signing.md), [T-342](T-342-disbursement-workflow.md), [T-132](T-132-mocks-personas-simple.md), [T-133](T-133-mocks-personas-large.md), [T-134](T-134-mocks-personas-garipov-quickstart.md), [T-135](T-135-mocks-technical-scenarios.md) |

## Цель

Исход и коды причин каждой из 9 персон и 10 технических сценариев проверены через HTTP на живых моках; цепочки с участием банка и клиента доходят до конца.

## Входит / не входит

- **Входит:** `api/tests/personas/`: персона → вход → заявка → ожидание → проверка исхода и кодов; цепочки `snabkontrakt`, `stankoprom`, `garipov`, `zarya`, `quick-start`; технические `t-*` через `POST /demo/scenarios` или встроенные сценарии; метки `TS-NNN`, сброс одной персоны перед тестом ([T-372](T-372-demo-reset-persona.md)).
- **Не входит:** браузерные e2e ([T-518](T-518-playwright-harness.md)).

## Входные документы

- [70-05](../../70-quality/05-integration-and-e2e.md): Интеграционные и сквозные тесты
- [10-02](../../10-product/02-personas.md): Персоны и ожидаемые исходы
- [30-17](../../30-decisioning/17-persona-walkthrough.md): Прохождение персон: тестовый оракул
- [70-04](../../70-quality/04-contract-and-api-tests.md): Контрактные тесты и тесты API

## Критерии приёмки

- [ ] Каждый стоп-фактор и флаг подтверждён хотя бы одним сценарием
- [ ] Прогон параллелится по персонам, внутри персоны — по порядку
- [ ] Исходы, коды и числа берутся из оракула [30-17](../../30-decisioning/17-persona-walkthrough.md); расхождение с [10-02](../../10-product/02-personas.md) фиксируется в таблице ожидаемых исходов
- [ ] Тесты написаны и зелёные (`make check`)
- [ ] Документация и OpenAPI обновлены, если менялся контракт
- [ ] Запись в журнале

## Тесты

persona (API).

## Заметки для реализации

- Чаос-тесты идут отдельным последовательным проходом ([70-05](../../70-quality/05-integration-and-e2e.md)).
