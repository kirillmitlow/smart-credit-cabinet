# Проверки проекта api/ (вызываются из корневого Makefile и CI)
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

.PHONY: check test coverage-md

check: ## Типы, границы модулей и быстрые тесты (без Docker)
	uv sync --frozen --quiet
	uv run mypy app
	uv run lint-imports
	uv run pytest -m "unit or property"

test: ## Все тесты с покрытием (порог в pyproject.toml), включая интеграционные (нужен Docker)
	uv sync --frozen --quiet
	uv run pytest --cov --cov-report=term-missing:skip-covered --cov-report=xml:reports/coverage.xml --junitxml=reports/junit.xml

coverage-md: ## Таблица покрытия в Markdown (для сводки CI; после `make test`)
	@uv run coverage report --format=markdown --skip-covered --fail-under=0
