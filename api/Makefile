# Проверки проекта api/ (вызываются из корневого Makefile и CI)
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

.PHONY: check test

check: ## Типы, границы модулей и быстрые тесты (без Docker)
	uv sync --frozen --quiet
	uv run mypy app
	uv run lint-imports
	uv run pytest -m "unit or property"

test: ## Все тесты, включая интеграционные на Postgres и Valkey (нужен Docker)
	uv sync --frozen --quiet
	uv run pytest
