"""Схема политики (T-281): источник у каждого числа, грейды без дыр, сверка с реестром 30-18."""

from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.modules.decisioning import PolicyError, parse_policy, policy_hash
from app.modules.pipeline import load_policy_file
from tests.fixtures.core_personas import POLICY_PATH, load_policy

pytestmark = pytest.mark.unit


def raw() -> dict[str, Any]:
    data = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return copy.deepcopy(data)


def test_v1_file_parses_and_has_all_sections() -> None:
    policy = load_policy()
    assert policy.meta.version == 1
    assert set(policy.catalog.products) == {
        "EXPRESS",
        "WORKING_CAPITAL",
        "CONTRACT",
        "CREDIT_LINE",
        "OVERDRAFT",
        "INVESTMENT",
    }


def test_every_cited_node_has_a_source() -> None:
    """Обход всего словаря: узел с `value`/числами без `source` и `note` не должен существовать."""

    def walk(node: Any, path: str) -> list[str]:
        problems: list[str] = []
        if isinstance(node, dict):
            if "value" in node and ("source" not in node or "note" not in node):
                problems.append(path)
            for key, child in node.items():
                problems.extend(walk(child, f"{path}.{key}"))
        elif isinstance(node, list):
            for i, child in enumerate(node):
                problems.extend(walk(child, f"{path}[{i}]"))
        return problems

    assert walk(raw(), "policy") == []


def test_number_without_source_is_rejected() -> None:
    data = raw()
    del data["pricing"]["key_rate"]["source"]
    with pytest.raises(PolicyError):
        parse_policy(data)


def test_source_must_be_traceable() -> None:
    data = raw()
    data["pricing"]["key_rate"]["source"] = "из головы"
    with pytest.raises(PolicyError, match="source"):
        parse_policy(data)


def test_float_instead_of_string_is_rejected() -> None:
    data = raw()
    data["pricing"]["key_rate"]["value"] = 0.14
    with pytest.raises(PolicyError, match="строкой"):
        parse_policy(data)


def test_unknown_key_is_rejected() -> None:
    data = raw()
    data["pricing"]["surprise"] = 1
    with pytest.raises(PolicyError):
        parse_policy(data)


def test_grades_must_cover_zero_to_hundred_without_holes() -> None:
    data = raw()
    data["master_scale"]["grades"][1]["max_points"] = 84  # дыра между B и A
    with pytest.raises(PolicyError, match="дыра"):
        parse_policy(data)
    data = raw()
    data["master_scale"]["grades"][-1]["min_points"] = 5  # E не доходит до нуля
    with pytest.raises(PolicyError, match="0–100"):
        parse_policy(data)
    data = raw()
    data["master_scale"]["grades"][0]["max_points"] = 99
    with pytest.raises(PolicyError, match="0–100"):
        parse_policy(data)


def test_pd_must_grow_from_a_to_e() -> None:
    data = raw()
    data["master_scale"]["grades"][0]["pd"] = "0.5"
    with pytest.raises(PolicyError, match="PD"):
        parse_policy(data)


def test_scorecard_maximums_sum_to_hundred() -> None:
    data = raw()
    data["scorecard"]["age"]["max_points"] = 13
    with pytest.raises(PolicyError, match="100"):
        parse_policy(data)


def test_bands_must_increase_and_end_open() -> None:
    data = raw()
    data["scorecard"]["age"]["bands"][1]["upto"] = "3"  # не по возрастанию
    with pytest.raises(PolicyError, match="возрастать"):
        parse_policy(data)
    data = raw()
    data["scorecard"]["age"]["bands"][-1]["upto"] = "99"
    with pytest.raises(PolicyError, match="без upto"):
        parse_policy(data)


def test_catalog_validations() -> None:
    data = raw()
    del data["catalog"]["products"]["OVERDRAFT"]
    with pytest.raises(PolicyError, match="ровно продукты"):
        parse_policy(data)
    data = raw()
    data["catalog"]["products"]["EXPRESS"]["grade_access"] = {"A": "AUTO"}
    with pytest.raises(PolicyError, match="A–E"):
        parse_policy(data)
    data = raw()
    data["catalog"]["products"]["EXPRESS"]["term_min_months"] = 99
    with pytest.raises(PolicyError, match="перепутаны"):
        parse_policy(data)
    data = raw()
    data["catalog"]["products"]["EXPRESS"]["grade_d_requires"] = "MAGIC"
    with pytest.raises(PolicyError, match="grade_d_requires"):
        parse_policy(data)


def test_authority_matrix_must_end_open_and_ascend() -> None:
    data = raw()
    data["routing"]["authority"][-1]["up_to_rub"] = 999
    with pytest.raises(PolicyError, match="без up_to_rub"):
        parse_policy(data)
    data = raw()
    data["routing"]["authority"][0]["up_to_rub"] = 99_000_000
    with pytest.raises(PolicyError, match="по возрастанию"):
        parse_policy(data)


def test_registry_30_18_matches_policy() -> None:
    """Сверка с реестром экономических параметров 30-18."""
    p = load_policy()
    assert p.pricing.key_rate.value == Decimal("0.14")  # №1: ключевая ставка на 20.10.2026
    assert p.pricing.spread.value == Decimal("0.01")  # №1а: ключевая + 1 п.п. = 15%
    assert p.pricing.lgd_unsecured.value == Decimal("0.45")  # №3
    assert p.pricing.lgd_secured.value == Decimal("0.35")  # №3а
    assert p.pricing.capital_charge.value == Decimal("0.02")  # №14а
    assert p.catalog.rate_corridor.value == Decimal("0.04")  # №16
    assert p.affordability.dscr_min.value == Decimal("1.25")  # №9
    assert p.affordability.stress_dscr_min.value == Decimal("1.0")  # №10
    schedule = {row.since: row.rate for row in p.features.vat.schedule}
    assert schedule == {date(2000, 1, 1): Decimal("0.20"), date(2026, 1, 1): Decimal("0.22")}  # №7
    assert p.features.industry.margins == {  # №5, D-079
        "TRADE": Decimal("0.05"),
        "FOOD": Decimal("0.10"),
        "MANUFACTURING": Decimal("0.12"),
        "IT": Decimal("0.15"),
        "AGRO": Decimal("0.15"),
        "SERVICES": Decimal("0.13"),
    }
    assert [r.pd for r in p.master_scale.grades] == [
        Decimal("0.01"),
        Decimal("0.03"),
        Decimal("0.07"),
        Decimal("0.15"),
        Decimal("0.30"),
    ]
    assert p.counter_offers.term_grid_months.value == (6, 12, 18, 24, 30, 36)  # №17
    assert p.counter_offers.dscr_min.value == Decimal("1.30")
    assert p.counter_offers.stress_dscr_min.value == Decimal("1.05")


def test_working_capital_term_is_three_to_thirty_six_months() -> None:
    """D-084: срок оборотного кредита 3–36 мес.; остальные границы — по 10-06."""
    p = load_policy()
    wc = p.product_config("WORKING_CAPITAL")
    assert (wc.term_min_months, wc.term_max_months) == (3, 36)
    assert (wc.amount_min_rub, wc.amount_max_rub) == (500_000, 30_000_000)
    ex = p.product_config("EXPRESS")
    assert (ex.amount_min_rub, ex.amount_max_rub, ex.term_min_months, ex.term_max_months) == (
        100_000,
        3_000_000,
        6,
        36,
    )
    assert p.product_config("CREDIT_LINE").collateral_required_above_rub == 15_000_000
    assert p.product_config("INVESTMENT").collateral_required_above_rub == 0
    assert p.product_config("OVERDRAFT").requires_bank_customer


def test_grade_lookup_boundaries() -> None:
    p = load_policy()
    expected = {
        100: "A",
        86: "A",
        85: "B",
        74: "B",
        73: "C",
        60: "C",
        59: "D",
        46: "D",
        45: "E",
        0: "E",
    }
    for points, grade in expected.items():
        assert p.grade_of(points).grade == grade
    with pytest.raises(ValueError, match="вне 0–100"):
        p.grade_of(101)
    with pytest.raises(ValueError, match="нет грейда"):
        p.grade_row("Z")


def test_policy_hash_is_stable_and_sensitive() -> None:
    base = raw()
    assert policy_hash(parse_policy(base)) == policy_hash(parse_policy(copy.deepcopy(base)))
    changed = copy.deepcopy(base)
    changed["pricing"]["key_rate"]["value"] = "0.15"
    assert policy_hash(parse_policy(changed)) != policy_hash(parse_policy(base))


def test_loader_reads_file_and_reports_problems(tmp_path: Path) -> None:
    assert load_policy_file(POLICY_PATH).meta.version == 1
    with pytest.raises(PolicyError, match="не удалось прочитать"):
        load_policy_file(tmp_path / "нет-такого-файла.yaml")
    broken = tmp_path / "broken.yaml"
    broken.write_text("a: [1, 2", encoding="utf-8")
    with pytest.raises(PolicyError, match="не удалось прочитать"):
        load_policy_file(broken)
    not_a_dict = tmp_path / "list.yaml"
    not_a_dict.write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(PolicyError, match="словарь"):
        load_policy_file(not_a_dict)
