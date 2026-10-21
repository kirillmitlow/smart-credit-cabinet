# Проверки проекта mocks/ (вызываются из корневого Makefile и CI)
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

.PHONY: check test

check: ## Типы и быстрые тесты (без Docker)
	uv sync --frozen --quiet
	uv run mypy app
	uv run pytest -m "not integration"

test: ## Все тесты, включая интеграционные на Postgres (нужен Docker)
	uv sync --frozen --quiet
	uv run pytest
