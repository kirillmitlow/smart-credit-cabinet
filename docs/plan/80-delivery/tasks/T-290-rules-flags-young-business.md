# T-290. Реализовать флаги и ограничение «молодой бизнес»

| | |
|---|---|
| Статус | TODO |
| Владелец | не назначен (Claude Code или Codex, по очереди смен) |
| Ветка | `feat/rules-flags-young-business` |
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

- [ ] `quick-start` → условное `COUNTER_OFFER` с `security_required`; `t-young-collateral` → `MANUAL_REVIEW`
- [ ] INV-61: флаг без стоп-фактора не даёт автоодобрения; INV-62: бизнес моложе 6 мес без обеспечения никогда `APPROVED`
- [ ] `t-mass`, `t-overdue-45`, `t-mismatch` дают ожидаемые флаги
- [ ] Тесты написаны и зелёные (`make check`)
- [ ] Документация и OpenAPI обновлены, если менялся контракт
- [ ] Запись в журнале

## Тесты

unit: все флаги и граница 6 мес.; property INV-61, INV-62.

## Заметки для реализации

- Какая сторона отвечает за `PIPELINE_ERROR`: ядро не вызывается, решение пишет pipeline ([30-04](../../30-decisioning/04-stop-factors-and-flags.md)).
