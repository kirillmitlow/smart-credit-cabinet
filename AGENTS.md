# Правила для ИИ-агентов

Проект: прототип цифрового кредитного конвейера для малого бизнеса (хакатон «Альфа-Будущее», кейс «Умный кредитный кабинет»). Дедлайн 26.10.2026.

**Перед любой работой прочитай:**
1. [docs/plan/00-meta/03-collaboration-protocol.md](docs/plan/00-meta/03-collaboration-protocol.md) — как работают агенты-сменщики (Claude Code и Codex). Обязательно.
2. [docs/plan/00-meta/08-handoff.md](docs/plan/00-meta/08-handoff.md) — **с какого места продолжать**.
3. [docs/plan/00-meta/07-journal.md](docs/plan/00-meta/07-journal.md) — последние записи и подсказки.
4. [docs/plan/00-meta/05-decisions-index.md](docs/plan/00-meta/05-decisions-index.md) — что уже решено. Не пересматривать.
5. [docs/plan/00-meta/04-planning-backlog.md](docs/plan/00-meta/04-planning-backlog.md) — какие документы нужны и в каком порядке.

**Коротко о главном:**
- Пиши код только по одобренным документам плана. Нашёл дыру — запиши вопрос в `docs/plan/00-meta/06-open-questions.md`, не выдумывай.
- Контракты моков — [docs/specs/mocks.md](docs/specs/mocks.md). Моки реализуем мы сами, строго по этому ТЗ, не перепроектируя его.
- ИИ не принимает кредитных решений. Ядро решения — детерминированное.
- В конце смены — перезаписать `08-handoff.md` и добавить запись в журнал.
- Пользователь не из банковской сферы и новичок в git: объясняй просто, документы без простыней кода.

## Код

Порядок работы — [реестр задач 80-01](docs/plan/80-delivery/01-work-breakdown.md) и [график 80-02](docs/plan/80-delivery/02-schedule.md). Готовность задачи — [80-04](docs/plan/80-delivery/04-definition-of-done.md).

**Команды** (нужны `uv` и Docker; один раз `make hooks` ставит git-хук):
- `make up` / `make down` — поднять и остановить стенд;
- `make check` — линтеры, типы, границы модулей, быстрые тесты; должен быть зелёным перед PR;
- `make test` — все тесты; `make openapi` — выгрузить OpenAPI и перегенерировать TS-клиент.

**Карта папок** ([подробно 50-03](docs/plan/50-architecture/03-repo-and-conventions.md)):

| Папка | Что |
|---|---|
| `api/` | Бэкенд FastAPI + Celery: `app/modules/<модуль>/`, `policy/`, `alembic/`, `tests/` |
| `mocks/` | Пять моков по [спецификации](docs/specs/mocks.md), отдельный Python-проект |
| `web/` | Фронт React + Mantine; `src/api/generated/` — сгенерированный клиент |
| `nlu/` | Сервис подсказок по свободному тексту (профиль `ai`) |
| `deploy/`, `scripts/`, `.github/` | Конфиги стенда, служебные скрипты, CI |

**Запреты:** не импортировать мимо границ модулей ([50-04](docs/plan/50-architecture/04-modules-and-boundaries.md)); не править `web/src/api/generated/` руками; не менять контракт (OpenAPI, схему БД, статусы, `policy`) без решения в реестре. «Сегодня» — только из часов приложения (`APP_TODAY`), `datetime.now()` запрещён линтером. Общие правила ruff — в корневом `ruff.toml`, проекты свой `[tool.ruff]` не заводят.

Перед кодом модуля прочитать раздел «Заметки для реализации» его документа в `docs/plan/50-architecture/`.
