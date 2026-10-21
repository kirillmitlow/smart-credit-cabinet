# T-401. Собрать образ `web`: Dockerfile и `nginx.conf` с прокси `/api` и SSE

| | |
|---|---|
| Статус | REVIEW — в ветке `feat/web-skeleton`; SSE через nginx проверен на тестовом источнике, настоящий поток ждёт T-352 |
| Владелец | не назначен (Claude Code или Codex, по очереди смен) |
| Ветка | `feat/web-dockerfile-nginx` |
| Оценка | ~3 ч |
| Приоритет | M (Must) |
| Тонкий сквозной сценарий | да |
| Зависит от | [T-400](T-400-web-skeleton.md) |

## Цель

Один origin для интерфейса и API: nginx отдаёт статику, проксирует `/api` в `api` и не буферизует SSE. Compose-сервис собирает [T-502](T-502-compose-main.md).

## Входит / не входит

- **Входит:** многоступенчатый Dockerfile (`pnpm install --frozen-lockfile`, сборка, nginx), непривилегированный запуск; `nginx.conf`: SPA-fallback, прокси `/api/` с `X-Request-Id`, для `/api/v1/events/stream` — `proxy_buffering off`, увеличенный `proxy_read_timeout`, HTTP/1.1; заголовки безопасности (CSP, `nosniff`, `frame-ancestors none`), кэширование статики по хешу.
- **Не входит:** сервис в compose ([T-502](T-502-compose-main.md)); Caddy и HTTPS облака ([T-507](T-507-compose-cloud.md)).

## Входные документы

- [50-14](../../50-architecture/14-deployment.md): Развёртывание
- [50-11](../../50-architecture/11-realtime.md): Живые статусы
- [50-09](../../50-architecture/09-security.md): Безопасность
- [50-01](../../50-architecture/01-overview.md): Архитектура: контейнеры и потоки данных

## Критерии приёмки

- [x] Через nginx SSE-событие доходит без задержки (ручная проверка и smoke) (проверено на тестовом источнике: события приходят раз в секунду, без накопления; настоящий поток — T-352)
- [x] Маршрут `/bank` и `/demo` отдаёт тот же `index.html` (SPA)
- [ ] Образ собирается без интернета после первой сборки (кроме регистра пакетов)
- [x] Тесты написаны и зелёные (`make check`)
- [x] Документация и OpenAPI обновлены, если менялся контракт
- [x] Запись в журнале

## Тесты

smoke: `docker run`, ответы `/` и `/api/v1/...`.

## Заметки для реализации

- Минимальная память ≈ 20 МБ, лимит 64 МБ ([50-01](../../50-architecture/01-overview.md)).
