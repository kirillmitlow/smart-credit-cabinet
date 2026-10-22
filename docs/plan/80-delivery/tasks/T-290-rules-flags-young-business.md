# T-290. Реализовать флаги и ограничение «молодой бизнес»

| | |
|---|---|
| Статус | DONE (ядро; запись `PIPELINE_ERROR` делает сторож `pipeline`, [T-271](T-271-pipeline-reaper-lease.md): ядро в этом случае не вызывается) |
| Владелец | не назначен (Claude Code или Codex, по очереди смен) |
| Ветка | `feat/decisioning-flags` (вместе с [T-288](T-288-features-consistency-antifraud.md)) |
| Оценка | ~4 ч |
| Приоритет | M (Must) |
| Тонкий сквозной сценарий | нет |
| Зависит от | [T-288](T-288-features-consistency-antifraud.md), [T-289](T-289-rules-stop-factors.md) |

## Цель

Флаги отправляют заявку человеку, не отказывая; ограничение `BUSINESS_TOO_YOUNG` даёт автоматическое встречное «с обеспечением» либо ручное рассмотрение.

## Входит / не входит

- **Входит:** флаги `MASS_REGISTRATION`, `OVERDUE_30_89`, `DATA_MISMATCH`, `TURNOVER_ANOMALY`, `SOURCE_UNAVAILABLE` (с указанием источника), `PIPELINE_ERROR` (создаёт pipeline); `BUSINESS_TOO_YOUNG` (< 6 мес): без обеспечения → условное встречное, даже при грейде C/D; с обеспечением → `MANUAL_REVIEW`; сильнее колонок каталога (D-077); флаги и стопы сильнее условного встречного; список обязательных источников и «необязательных» по [30-04](../../30-decisioning/04-stop-factors-and-flags.md).
- **Не входит:** сборка маршрута ([T-296](T-296-routing-authority.md)).

## Входные документы

- [30-04](../../30-decisioning/04-stop-factors-and-flags.md): Стоп-факторы, флаги и ограничение
- [10-06](../../10-product/06-product-catalog.md): Каталог продуктов
- [00-05](../../00-meta/05-decisions-index.md): Реестр решений
- [10-02](../../10-product/02-personas.md): Персоны и ожидаемые исходы

## Критерии приёмки

- [x] `quick-start` → условное `COUNTER_OFFER` с `security_required`; `t-young-collateral` → `MANUAL_REVIEW`
- [x] INV-61: флаг без стоп-фактора не даёт автоодобрения; INV-62: бизнес моложе 6 мес без обеспечения никогда `APPROVED`
- [x] `t-mass`, `t-overdue-45`, `t-mismatch` дают ожидаемые флаги
- [x] Тесты написаны и зелёные (`make check`)
- [x] Документация и OpenAPI обновлены, если менялся контракт (схема ответа не менялась; клиентский вид скрывает коды антифрода, [R-004](../../reviews/R-004-core-implementation-notes.md), пункт 12)
- [x] Запись в журнале

## Тесты

unit: все флаги и граница 6 мес.; property INV-61, INV-62.

## Заметки для реализации

- Какая сторона отвечает за `PIPELINE_ERROR`: ядро не вызывается, решение пишет pipeline ([30-04](../../30-decisioning/04-stop-factors-and-flags.md)).
- Флаги `MASS_REGISTRATION`, `OVERDUE_30_89`, `DATA_MISMATCH`, `TURNOVER_ANOMALY` — `api/app/modules/decisioning/flags.py`; `SOURCE_UNAVAILABLE` — `eligibility.unavailable_sources` (список обязательных источников сверен с 30-04); `BUSINESS_TOO_YOUNG` и его приоритет над колонками каталога, флагами и стопами — `routing.route` ([T-296](T-296-routing-authority.md)).
- Приоритет проверен тестами: стоп-фактор → `NEEDS_INFO` → условное встречное → ручные причины. Флаг без стопа не даёт автоодобрения (INV-61 на настоящих флагах), молодой бизнес без обеспечения не получает `APPROVED` (INV-62).
