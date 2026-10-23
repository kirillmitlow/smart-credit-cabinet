# Единый вход для агентов-разработчиков (50-03). Жюри Makefile не нужен: у него `docker compose up` (D-064).
# Те же команды выполняет CI (.github/workflows/ci.yml): флагов «только локально» здесь нет.

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

PRE_COMMIT := uvx pre-commit@4.7.0
PY_SCRIPTS := uv run --python 3.13 --no-project --with pytest==9.1.1 python
# Python-проекты монорепозитория; каждый со своим pyproject.toml и uv.lock (50-03)
PY_PROJECTS := $(foreach p,api mocks nlu,$(if $(wildcard $(p)/pyproject.toml),$(p)))
# SKIP_WEB=1: не гонять фронт (в CI его проверяет отдельное задание `web`, там ставятся Node и pnpm)
HAS_WEB := $(if $(SKIP_WEB),,$(wildcard web/package.json))
HAS_COMPOSE := $(wildcard docker-compose.yml)

.PHONY: help up down check lint docs-check test fmt openapi openapi-check reset hooks

help: ## Список команд
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-11s %s\n", $$1, $$2}'

hooks: ## Установить git-хук pre-commit (один раз на ПК)
	$(PRE_COMMIT) install

up: ## Поднять стенд
ifeq ($(HAS_COMPOSE),)
	@echo "docker-compose.yml ещё нет (задача T-502): поднимать нечего"
else
	docker compose up -d --build --wait
endif

down: ## Остановить стенд
ifeq ($(HAS_COMPOSE),)
	@echo "docker-compose.yml ещё нет (задача T-502)"
else
	docker compose down
endif

lint: ## Быстрые проверки pre-commit на всех файлах
	$(PRE_COMMIT) run --all-files --show-diff-on-failure

docs-check: ## Ссылки в документах
	$(PY_SCRIPTS) scripts/check_docs.py

check: lint docs-check ## Всё, что должно быть зелёным перед PR: линтеры, типы, границы, быстрые тесты
	$(PY_SCRIPTS) -m pytest -q scripts/tests
	@for p in $(PY_PROJECTS); do $(MAKE) --no-print-directory -C $$p check; done
	$(MAKE) --no-print-directory openapi-check
ifneq ($(HAS_WEB),)
	$(MAKE) --no-print-directory -C web check
endif

test: check ## Все тесты (включая медленные)
	@for p in $(PY_PROJECTS); do $(MAKE) --no-print-directory -C $$p test; done
ifneq ($(HAS_WEB),)
	$(MAKE) --no-print-directory -C web test
endif

fmt: ## Автоформат
	uvx ruff@0.17.1 check --fix .
	uvx ruff@0.17.1 format .
ifneq ($(HAS_WEB),)
	$(MAKE) --no-print-directory -C web fmt
endif

openapi: ## Выгрузить OpenAPI в docs/api и перегенерировать TS-клиент
	uv run --directory api python export_openapi.py
	$(MAKE) --no-print-directory -C web gen-api

openapi-check: ## Проверить, что все шесть схем совпадают с кодом (без БД и стенда)
	uv run --directory api python export_openapi.py --check

reset: ## Сброс демо-стенда
	curl -fsS -X POST http://127.0.0.1:8100/demo/reset && echo
