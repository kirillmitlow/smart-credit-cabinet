"""T-120: согласованность реквизитов, людей и тела registry, независимо от HTTP/БД."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.common.inn import inn_is_valid, ogrn_is_valid
from app.main import create_app
from app.roles.registry.admin import RegistryHandler
from app.roles.registry.schemas import RegistryBody
from app.roles.scenarios.expand import expand, resolved_spec
from app.roles.scenarios.schemas import ScenarioSpec
from app.settings import Settings

TODAY = date(2026, 10, 25)


def scenario(**overrides: Any) -> ScenarioSpec:
    return ScenarioSpec.model_validate(
        {"code": "identity-test", "title": "Тест", "preset": "LLC_HEALTHY", **overrides}
    )


def checked(
    spec: ScenarioSpec, today: date = TODAY, reserved: set[str] | None = None
) -> dict[str, Any]:
    result = expand(spec, today, reserved)
    body = RegistryBody.model_validate(result["registry"])
    RegistryHandler().check(result["identity"]["inn"], body)
    return result


@pytest.mark.parametrize(
    "preset",
    [
        "LLC_HEALTHY",
        "IP_HEALTHY",
        "LLC_HIGH_DEBT_LOAD",
        "STARTUP",
        "SELF_EMPLOYED",
        "PROBLEM_DEBTOR",
    ],
)
def test_presets_produce_valid_repeatable_registry(preset: str) -> None:
    """TS-109: реквизиты синтетические, контрольные суммы верны."""
    spec = scenario(preset=preset)
    first = checked(spec)
    assert json.dumps(first, ensure_ascii=False) == json.dumps(checked(spec), ensure_ascii=False)
    identity = first["identity"]
    assert inn_is_valid(identity["inn"])
    assert identity["inn"].startswith("00")
    if identity["ogrn"]:
        assert ogrn_is_valid(identity["ogrn"])
        assert identity["ogrn"][3:5] == "00"
        assert int(identity["ogrn"][1:3]) == int(identity["registrationDate"][:4]) % 100
    for person in identity["persons"]:
        assert inn_is_valid(person["inn"])
        assert person["inn"].startswith("00")
        birth = date.fromisoformat(person["birthDate"])
        assert (
            25
            <= TODAY.year - birth.year - ((TODAY.month, TODAY.day) < (birth.month, birth.day))
            <= 65
        )


@pytest.mark.parametrize("form", ["LLC", "JSC", "IP", "SELF_EMPLOYED"])
def test_forms_and_subject_links(form: str) -> None:
    result = checked(scenario(preset=None, company={"form": form}))
    identity = result["identity"]
    if form in ("IP", "SELF_EMPLOYED"):
        assert identity["kpp"] is identity["director"] is None
        assert identity["founders"] == []
    if form == "IP":
        assert identity["owner"]["inn"] == identity["inn"]
        assert identity["subjectRefs"]["company"] == identity["subjectRefs"]["owner"]
        assert result["registry"]["entity"]["person"]["fullName"] == identity["owner"]["fullName"]
    elif form == "SELF_EMPLOYED":
        assert identity["ogrn"] is None
        assert result["registry"]["entity"] is None
    elif form == "JSC":
        assert identity["owner"] is None
        assert identity["founders"] == []
        assert len(identity["persons"]) == 1
    else:
        assert identity["owner"]["inn"] == identity["director"]["inn"]
        assert len(identity["persons"]) == 1
        assert identity["founders"][0]["sharePercent"] == 100
    entity = result["registry"]["entity"]
    if form in ("LLC", "JSC"):
        assert entity["kpp"][:4] == entity["inn"][:4] == entity["taxAuthority"]["code"]


def test_absolute_date_overrides_preset_age_and_keeps_explicit_fields() -> None:
    spec = scenario(
        company={
            "name": "СтанкоПром",
            "inn": "0017654322",
            "ogrn": "1170000004569",
            "kpp": "001701001",
            "registrationDate": "2017-03-14",
            "okved": "25.62",
            "regionCode": "66",
        },
        people={
            "director": {
                "ref": "kuznetsov",
                "inn": "001310000115",
                "fullName": "Кузнецов Игорь Петрович",
                "birthDate": "1979-02-11",
                "sharePercent": 100,
            }
        },
    )
    result = checked(spec)
    entity = result["registry"]["entity"]
    assert (
        entity["registrationDate"]
        == entity["status"]["since"]
        == entity["director"]["since"]
        == "2017-03-14"
    )
    assert entity["shortName"] == "ООО «СтанкоПром»"
    assert entity["address"]["regionCode"] == "66"
    assert entity["ogrn"] == "1170000004569"
    assert result["identity"]["subjectRefs"]["owner"] == "001310000115"
    assert resolved_spec(spec).company.age_months is None


def test_relative_dates_recomputed_without_changing_inns() -> None:
    spec = scenario(preset="STARTUP")
    before = checked(spec)
    after = checked(spec, date(2027, 4, 25))
    assert before["identity"]["registrationDate"] == "2026-07-25"
    assert after["identity"]["registrationDate"] == "2027-01-25"
    assert before["identity"]["inn"] == after["identity"]["inn"]
    assert before["identity"]["director"]["inn"] == after["identity"]["director"]["inn"]
    assert after["identity"]["ogrn"][1:3] == "27"


def test_flags_have_structured_grn_and_dates() -> None:
    entity = checked(scenario(company={"unreliableAddress": True, "pendingExclusion": True}))[
        "registry"
    ]["entity"]
    assert entity["address"]["unreliable"]["since"] == TODAY.isoformat()
    for grn in (entity["address"]["unreliable"]["grn"], entity["pendingExclusion"]["grn"]):
        assert grn.startswith("22600")
        assert len(grn) == 13
        assert grn[-1] == str(int(grn[:-1]) % 11 % 10)
    assert entity["lastRecord"]["grn"] == entity["pendingExclusion"]["grn"]
    assert entity["pendingExclusion"]["objectionsDeadline"] == "2027-01-25"


def test_owner_is_largest_share_and_tie_is_first() -> None:
    founders = [{"ref": "first", "sharePercent": 40}, {"ref": "second", "sharePercent": 60}]
    result = checked(scenario(people={"founders": founders}))["identity"]
    assert result["owner"]["ref"] == "second"
    assert result["owner"]["inn"] != result["director"]["inn"]
    tied = checked(
        scenario(
            people={
                "founders": [
                    {"ref": "first", "sharePercent": 50},
                    {"ref": "second", "sharePercent": 50},
                ]
            }
        )
    )["identity"]
    assert tied["owner"]["ref"] == "first"


def test_director_and_founder_merge_explicit_details_by_ref_or_inn() -> None:
    for director in ({"ref": "same"}, {"inn": "001310000115", "ref": "boss"}):
        result = checked(
            scenario(
                people={
                    "director": director,
                    "founders": [
                        {
                            "ref": "same",
                            "inn": "001310000115",
                            "fullName": "Кузнецов Игорь Петрович",
                            "birthDate": "1979-02-11",
                        }
                    ],
                }
            )
        )["identity"]
        assert len(result["persons"]) == 1
        assert result["director"]["fullName"] == "Кузнецов Игорь Петрович"
        assert result["director"]["birthDate"] == "1979-02-11"
        assert result["subjectRefs"]["director"] == result["subjectRefs"]["owner"]


@pytest.mark.parametrize(
    "company",
    [
        {"ogrn": "1170000004569"},
        {"ogrn": "1170000004569", "registrationDate": "2018-03-14"},
        {"ogrn": "1170000004560", "registrationDate": "2017-03-14"},
        {"inn": "0017654320"},
        {"inn": "7707083893"},
        {"inn": "0017654322", "kpp": "009901001"},
        {"registrationDate": "2027-01-01"},
        {"status": "CEASED"},
    ],
)
def test_invalid_identifiers_and_dates_rejected(company: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="ОГРН|ogrn|ИНН|КПП|регистрации|status"):
        expand(scenario(company=company), TODAY)


@pytest.mark.parametrize(
    "people_spec",
    [
        {"founders": []},
        {"founders": [{"sharePercent": 40}, {"sharePercent": 40}]},
        {"founders": [{"sharePercent": 100}, {}]},
        {"founders": [{"ref": "same"}, {"ref": "same"}]},
        {
            "director": {"ref": "same", "fullName": "Иванов Иван"},
            "founders": [{"ref": "same", "fullName": "Петров Пётр"}],
        },
        {"director": {"birthDate": "2027-01-01"}},
    ],
)
def test_invalid_people_rejected(people_spec: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="дол|Дол|учредител|Противоречивые|рождения"):
        expand(scenario(people=people_spec), TODAY)


@given(count=st.integers(1, 20), fixed=st.integers(1, 90))
def test_generated_shares_sum_to_100(count: int, fixed: int) -> None:
    founders = [{"ref": "fixed", "sharePercent": fixed}] + [
        {"ref": f"other-{i}"} for i in range(count)
    ]
    expanded = checked(scenario(people={"founders": founders}))
    result = expanded["identity"]
    assert result["founders"][0]["sharePercent"] == fixed
    assert sum(p["sharePercent"] for p in result["founders"]) == pytest.approx(100, abs=1e-9)
    assert all(p["sharePercent"] > 0 for p in result["founders"])
    entity = expanded["registry"]["entity"]
    assert sum(p["shareNominalRub"] for p in entity["founders"]) == entity["authorizedCapitalRub"]


def test_1000_scenarios_have_unique_company_and_person_inns() -> None:
    used: set[str] = set()
    for i in range(1000):
        result = checked(
            scenario(code=f"batch-{i}", preset="IP_HEALTHY" if i % 2 else "LLC_HEALTHY"),
            reserved=used,
        )["identity"]
        current = {result["inn"]} | {p["inn"] for p in result["persons"]}
        assert not current & used
        used.update(current)
    assert len(used) == 1500


def test_collision_retries_and_explicit_inn_is_never_replaced() -> None:
    first = checked(scenario())["identity"]
    occupied = {first["inn"]}
    alternative = checked(scenario(), reserved=occupied)["identity"]
    assert alternative["inn"] != first["inn"]
    assert alternative == checked(scenario(), reserved=occupied)["identity"]
    with pytest.raises(ValueError, match="занят"):
        expand(scenario(company={"inn": first["inn"]}), TODAY, occupied)


def test_missing_form_or_preset_is_rejected_and_preset_not_mutated() -> None:
    with pytest.raises(ValueError, match="company.form"):
        scenario(preset=None)
    first = checked(scenario())
    checked(scenario(company={"ageMonths": 1, "name": "Другое"}))
    assert checked(scenario()) == first


def test_scenarios_openapi_matches_saved_contract() -> None:
    path = Path(__file__).resolve().parents[2] / "docs/api/mock-scenarios.openapi.yaml"
    actual = create_app(Settings(mock_role="scenarios", database_url=None)).openapi()
    assert actual == json.loads(path.read_text())
