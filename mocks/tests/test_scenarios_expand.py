"""T-125: полный pipeline использует общие личности и пригодные для записи тела."""

from datetime import date

import pytest

from app.roles.bank_core.admin import BankCoreAdminHandler
from app.roles.bank_core.schemas import BankCoreBody
from app.roles.bki.admin import BkiAdminHandler
from app.roles.bki.schemas import BkiSubjectBody
from app.roles.registry.admin import RegistryHandler
from app.roles.registry.schemas import RegistryBody
from app.roles.scenarios.expand import expand
from app.roles.scenarios.schemas import Preset, ScenarioSpec
from app.roles.tax.admin import TaxHandler
from app.roles.tax.schemas import TaxBody

TODAY = date(2026, 10, 25)


@pytest.mark.parametrize("preset", list(Preset))
def test_all_presets_expand_into_repeatable_valid_role_bodies(preset: Preset) -> None:
    spec = ScenarioSpec(title="Полный предпросмотр пресета", preset=preset)
    data = expand(spec, TODAY)
    assert data == expand(spec, TODAY)
    inn = data["identity"]["inn"]
    RegistryHandler().check(inn, RegistryBody.model_validate(data["registry"]))
    TaxHandler().check(inn, TaxBody.model_validate(data["tax"]))
    BankCoreAdminHandler().check(inn, BankCoreBody.model_validate(data["bankCore"]))
    for entry in data["bki"]:
        BkiAdminHandler().check(entry["inn"], BkiSubjectBody.model_validate(entry["body"]))
    for entry in data["bankSubjects"]:
        BankCoreAdminHandler().check(entry["inn"], BankCoreBody.model_validate(entry["body"]))
    known = {inn, *[p["inn"] for p in data["identity"]["persons"]]}
    assert all(entry["inn"] in known for entry in data["bki"] + data["bankSubjects"])


def test_own_bank_loan_is_shared_between_bki_and_core_in_full_pipeline() -> None:
    spec = ScenarioSpec.model_validate(
        {
            "title": "Кредит нашего банка",
            "company": {"form": "LLC", "ageMonths": 60},
            "bank": {"isCustomer": True},
            "bki": {
                "company": {
                    "activeLoans": [{"kind": "LOAN", "amountRub": 3000000, "ourBank": True}]
                }
            },
        }
    )
    data = expand(spec, TODAY)
    obligation = data["bki"][0]["body"]["obligations"][0]
    loan = data["bankCore"]["loans"][0]
    assert loan["contractUid"] == obligation["uid"]
    assert loan["amountRub"] == obligation["amountRub"] == 3000000
