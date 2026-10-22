# Фронтенд (T-400…T-407). Корневой Makefile зовёт `make -C web check` и `make -C web test`, пока есть web/package.json.
# Менеджер пакетов — pnpm (версия закреплена в package.json: `packageManager`); в CI его ставит pnpm/action-setup.

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

PNPM ?= pnpm
STAMP := node_modules/.install-stamp

.PHONY: help install check test fmt gen-api build dev e2e e2e-install

help: ## Список команд
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make -C web %-11s %s\n", $$1, $$2}'

$(STAMP): package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc
	$(PNPM) install --frozen-lockfile
	@touch $(STAMP)

install: $(STAMP) ## Поставить зависимости строго по lock-файлу

check: install ## ESLint, Prettier, tsc --noEmit, клиент совпадает со схемой, быстрые тесты (Vitest)
	$(PNPM) lint
	$(PNPM) format:check
	$(PNPM) typecheck
	$(PNPM) gen:api:check
	$(PNPM) test

test: check ## Всё из check + покрытие не ниже 70%, сборка
	$(PNPM) test:coverage
	$(PNPM) build

fmt: install ## Автоформат (Prettier и ESLint --fix)
	$(PNPM) format
	$(PNPM) exec eslint . --fix

gen-api: install ## Перегенерировать клиент из docs/api/api.openapi.json (orval)
	$(PNPM) gen:api

build: install ## Собрать статику в dist/
	$(PNPM) build

dev: install ## Vite dev-сервер на :5173; /api идёт в api на 127.0.0.1:8100
	$(PNPM) dev

e2e-install: install ## Поставить браузер Chromium для e2e (один раз на машину)
	$(PNPM) e2e:install

e2e: install ## Сквозные тесты в браузере (Playwright) против поднятого стенда; в check и test не входят
	@echo "Стенд должен быть поднят: WEB_PORT=8088 docker compose -p scc-pw up -d --build --wait"
	@echo "Адрес стенда: E2E_BASE_URL (по умолчанию http://localhost:8080)"
	$(PNPM) e2e
