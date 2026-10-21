# T-511. Подключить в CI проверки контрактов, безопасности и THIRD_PARTY_NOTICES

| | |
|---|---|
| Статус | TODO |
| Владелец | Агент A/B (любой сменщик) |
| Ветка | `chore/ci-contracts-security-notices` |
| Оценка | ~5 ч |
| Зависит от | [T-509](T-509-ci-skeleton.md), [T-139](T-139-mocks-openapi-export.md), [T-524](T-524-third-party-notices.md), [T-543](T-543-make-openapi-all.md), [70-04](../../70-quality/04-contract-and-api-tests.md) |
| Приоритет | M (Must) |
| Веха | V6 ([график](../02-schedule.md)) |

## Цель

Три «страховки от молчаливого расхождения»: схема API против кода, уязвимости и секреты, лицензии против lock-файлов.

## Входит / не входит

- **Входит:**
  - Задание `openapi`: выгрузка OpenAPI `api` и пяти моков, сверка с `docs/api/`, `oasdiff` против `main` (поля `v1` не удаляем), Spectral (`operationId`, ошибки, схемы безопасности, `camelCase`), orval-дифф клиента и `tsc --noEmit`
  - Задание `security`: `gitleaks`, `pip-audit` по `uv.lock`, `pnpm audit --prod`, `trivy fs` и `trivy config`, после `build` — `trivy image`; блокируют HIGH/CRITICAL с исправлением
  - Задание `notices`: `THIRD_PARTY_NOTICES` соответствует lock-файлам (скрипт [T-524](T-524-third-party-notices.md))
  - Файл правил Spectral в репозитории; кэш базы `trivy`
- **Не входит:**
  - Сами скрипты выгрузки ([T-139](T-139-mocks-openapi-export.md), [T-543](T-543-make-openapi-all.md)) и генератор уведомлений ([T-524](T-524-third-party-notices.md))

## Входные документы

- [70-04](../../70-quality/04-contract-and-api-tests.md) (таблица проверок 1–6)
- [70-08](../../70-quality/08-ci-pipeline.md)
- [50-09](../../50-architecture/09-security.md) (цепочка поставки)

## Критерии приёмки

- [ ] Изменение ручки без обновления `docs/api/*.yaml` делает задание `openapi` красным
- [ ] Удаление поля схемы без смены версии даёт красный `oasdiff`
- [ ] Добавленный в тестовом коммите фальшивый секрет ловит `gitleaks`
- [ ] Добавление зависимости без обновления `THIRD_PARTY_NOTICES` ломает `notices`
- [ ] Отчёты `trivy`, аудита и Spectral лежат артефактами на 14 дней
- [ ] Тесты написаны и зелёные
- [ ] Документация и OpenAPI обновлены, если менялся контракт
- [ ] Запись в журнале
- [ ] Выполнено [определение готовности](../04-definition-of-done.md) (линтеры, PR по шаблону, статус задачи обновлён)

## Тесты

Проверка на искусственных нарушениях в тестовых ветках.

## Заметки для реализации

- Фронт использует `pnpm`, поэтому «`npm audit`» из 50-09 читать как `pnpm audit` (заметка в 70-08).
- `trivy image` нужен только после `build`; не запускайте его на каждом промежуточном слое.
