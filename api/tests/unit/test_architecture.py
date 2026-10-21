"""Границы модулей (50-04): чужой модуль — только через публичный __init__; владение таблицами (R5);
чистота ядра (R2): decide() без сети даёт одинаковый результат."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.modules.decisioning import decide, input_to_json
from app.shared.db import Base
from app.shared.tables import TABLE_OWNERS
from tests.conftest import NetworkForbiddenError
from tests.fixtures.core_personas import sokolova

pytestmark = pytest.mark.unit

MODULES = Path(__file__).resolve().parents[2] / "app" / "modules"


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
            names.extend(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
    return names


def find_violations(modules_dir: Path) -> list[str]:
    problems = []
    for file in modules_dir.rglob("*.py"):
        owner = file.relative_to(modules_dir).parts[0]
        for name in _imports(file):
            parts = name.split(".")
            if parts[:2] != ["app", "modules"] or len(parts) < 4:
                continue
            target, inner = parts[2], parts[3]
            if target != owner and inner in {"repo", "domain", "models", "router", "service"}:
                problems.append(f"{file.relative_to(modules_dir)} → app.modules.{target}.{inner}")
    return sorted(set(problems))


def test_modules_use_only_public_interfaces() -> None:
    assert find_violations(MODULES) == []


def test_rule_catches_foreign_repo_import(tmp_path: Path) -> None:
    (tmp_path / "offers").mkdir()
    (tmp_path / "offers" / "service.py").write_text("from app.modules.applications.repo import x\n")
    assert find_violations(tmp_path) == ["offers/service.py → app.modules.applications.repo"]


def test_every_table_has_exactly_one_owner() -> None:
    import app.shared.models  # noqa: F401 — регистрирует таблицы

    tables = set(Base.metadata.tables)
    assert tables == set(TABLE_OWNERS), (
        "Таблица без владельца в shared/tables.py или лишний владелец"
    )


@pytest.mark.usefixtures("no_network")
def test_decide_is_pure_without_network() -> None:
    import socket

    with pytest.raises(NetworkForbiddenError):
        socket.create_connection(("example.org", 80))
    inputs = sokolova()
    first, second = decide(inputs), decide(inputs)
    assert first == second
    assert repr(first) == repr(second)  # побайтно: порядок причин и числа те же (INV-50, INV-51)
    assert input_to_json(inputs) == input_to_json(inputs)
