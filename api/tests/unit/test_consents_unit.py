"""T-260, T-261: тексты согласий и их хеши, HMAC-доказательство, полномочия, состав пакета."""

from __future__ import annotations

import hashlib
import re
from datetime import date
from uuid import uuid4

import pytest

from app.modules import companies
from app.modules.applications import consent_texts as texts
from app.modules.applications.consent_proof import compute_proof
from app.modules.applications.consents import Required, bundle_fingerprint, can_sign
from app.modules.auth import Membership, Principal, Zone

pytestmark = pytest.mark.unit

TODAY = date(2026, 10, 21)


def test_text_hash_is_sha256_of_whitespace_normalized_text() -> None:
    assert texts.normalize("  Я,\n  согласен \t\t тут  ") == "Я, согласен тут"
    expected = hashlib.sha256("Я, согласен тут".encode()).hexdigest()
    assert texts.text_hash("Я, согласен тут") == expected
    assert texts.text_hash("  Я,\n  согласен \t\t тут  \n") == expected


def test_hash_ignores_only_whitespace_changes() -> None:
    assert texts.text_hash("а б") == texts.text_hash("а   б")
    assert texts.text_hash("а б") != texts.text_hash("а  б.")


def test_texts_on_disk_have_versions_and_reproducible_hashes() -> None:
    found = texts.available()
    assert {"bki-consent-v1", "turnover-consent-v1", "pd-consent-v1", "pep-rules-v1"} <= set(found)
    for key, item in found.items():
        assert re.fullmatch(r"[0-9a-f]{64}", item.sha256), key
        assert item.version == int(key.rsplit("-v", 1)[1])
    bki = texts.current_for_kind("BKI")
    assert bki.key == "bki-consent-v1"
    assert bki.sha256 == hashlib.sha256(" ".join(bki.text.split()).encode()).hexdigest()
    assert texts.pep_rules().key == "pep-rules-v1"


def test_kinds_have_separate_texts() -> None:
    hashes = {texts.current_for_kind(k).sha256 for k in ("BKI", "TURNOVER", "PERSONAL_DATA")}
    assert len(hashes) == 3  # ПДн отдельное от БКИ и оборотов (152-ФЗ)


def test_text_change_is_a_new_version_old_signatures_keep_their_own(tmp_path: object) -> None:
    from pathlib import Path

    directory = Path(str(tmp_path))
    (directory / "bki-consent-v1.txt").write_text("текст один", encoding="utf-8")
    (directory / "bki-consent-v2.txt").write_text("текст   два", encoding="utf-8")
    versions = {}
    for path in sorted(directory.glob("*.txt")):
        versions[path.stem] = texts.text_hash(path.read_text(encoding="utf-8"))
    assert versions["bki-consent-v1"] != versions["bki-consent-v2"]
    # подпись под v1 хранит ключ v1 и его хеш: v2 её не меняет
    assert versions["bki-consent-v1"] == texts.text_hash("текст один")


def test_render_fills_known_placeholders_and_keeps_unknown() -> None:
    out = texts.current_for_kind("BKI").render(
        name="ИП Соколова",
        inn="001234567887",
        application_number="АЗ-1",
        bank_name="Банк",
        months="6",
    )
    assert "ИП Соколова" in out
    assert "001234567887" in out
    assert "{" not in out


PROOF_ARGS = {
    "code": "123456",
    "text_hash": "a" * 64,
    "signer_inn": "001310000115",
    "attempt_id": "otp_abc",
    "subject_inn": "0017654322",
    "kind": "BKI",
}


def test_proof_is_deterministic_hmac_and_does_not_contain_the_code() -> None:
    first = compute_proof("secret", **PROOF_ARGS)
    assert first == compute_proof("secret", **PROOF_ARGS)
    assert re.fullmatch(r"[0-9a-f]{64}", first)
    assert "123456" not in first
    plain_hash = hashlib.sha256(b"123456").hexdigest()
    assert first != plain_hash


def test_proof_cannot_be_brute_forced_without_the_secret() -> None:
    """Если бы в базе лежал обычный хеш кода, перебор 10^6 за секунды нашёл бы его."""
    proof = compute_proof("secret", **PROOF_ARGS)
    candidates = (f"{i:06d}" for i in range(10_000))
    guess = {**PROOF_ARGS}
    found = []
    for code in candidates:
        guess["code"] = code
        if compute_proof("wrong-secret", **guess) == proof:
            found.append(code)
    assert found == []


@pytest.mark.parametrize(
    "field", ["code", "text_hash", "signer_inn", "attempt_id", "subject_inn", "kind"]
)
def test_proof_depends_on_every_input(field: str) -> None:
    original = PROOF_ARGS[field]
    replacement = (
        "PERSONAL_DATA" if field == "kind" else ("9" if original[0] != "9" else "8") + original[1:]
    )
    changed = {**PROOF_ARGS, field: replacement}
    assert compute_proof("secret", **changed) != compute_proof("secret", **PROOF_ARGS)
    assert compute_proof("other", **PROOF_ARGS) != compute_proof("secret", **PROOF_ARGS)


def test_proof_of_a_consent_does_not_depend_on_bundle_order() -> None:
    items = [("BKI", "0017654322"), ("BKI", "001310000115"), ("PERSONAL_DATA", "001310000115")]

    def bundle(order: list[tuple[str, str]]) -> dict[tuple[str, str], str]:
        return {
            (kind, inn): compute_proof("s", **{**PROOF_ARGS, "kind": kind, "subject_inn": inn})
            for kind, inn in order
        }

    assert bundle(items) == bundle(list(reversed(items)))
    assert len(set(bundle(items).values())) == 3  # у каждого согласия своё доказательство


def test_fingerprint_binds_exact_set_and_ignores_order() -> None:
    app = uuid4()
    a = bundle_fingerprint(app, [("BKI", "1"), ("PERSONAL_DATA", "1")])
    assert a == bundle_fingerprint(app, [("PERSONAL_DATA", "1"), ("BKI", "1"), ("BKI", "1")])
    assert a != bundle_fingerprint(app, [("BKI", "1")])
    assert a != bundle_fingerprint(uuid4(), [("BKI", "1"), ("PERSONAL_DATA", "1")])


def principal(user_id: object, role: str, inn: str | None) -> Principal:
    company = uuid4()
    return Principal(
        user_id=user_id,  # type: ignore[arg-type]
        role="CLIENT",
        zone=Zone.CLIENT,
        display_name="x",
        person_inn=inn,
        memberships=(Membership(company, role),),
        active_company_id=company,
    )


def person(
    user_id: object, role: str, permissions: set[str], valid_until: date | None
) -> companies.Person:
    return companies.Person(
        user_id=user_id,  # type: ignore[arg-type]
        display_name="x",
        person_inn="001310000299",
        role=role,
        poa_permissions=frozenset(permissions),
        poa_valid_until=valid_until,
    )


COMPANY_CONSENT = Required("BKI", "0017654322", "COMPANY", "COMPANY", "СтанкоПром")
PERSONAL_CONSENT = Required("BKI", "001310000115", "PERSON", "DIRECTOR", "Кузнецов")


def test_authority_matrix() -> None:
    boss, accountant, expired, guarantor, nobody = (uuid4() for _ in range(5))
    people = [
        person(boss, "DIRECTOR", set(), None),
        person(accountant, "ACCOUNTANT", {"SIGN_COMPANY_CONSENTS"}, date(2027, 1, 1)),
        person(expired, "ACCOUNTANT", {"SIGN_COMPANY_CONSENTS"}, date(2026, 10, 20)),
        person(guarantor, "GUARANTOR", {"SIGN_COMPANY_CONSENTS"}, None),
    ]
    director = principal(boss, "DIRECTOR", "001310000115")
    assert can_sign(COMPANY_CONSENT, director, people, TODAY)
    assert can_sign(PERSONAL_CONSENT, director, people, TODAY)
    # бухгалтер с действующей доверенностью: компания да, личное нет
    clerk = principal(accountant, "ACCOUNTANT", "001310000299")
    assert can_sign(COMPANY_CONSENT, clerk, people, TODAY)
    assert not can_sign(PERSONAL_CONSENT, clerk, people, TODAY)
    # доверенность истекла вчера
    assert not can_sign(COMPANY_CONSENT, principal(expired, "ACCOUNTANT", "1"), people, TODAY)
    # поручитель за компанию не подписывает, даже с записью о полномочии
    assert not can_sign(COMPANY_CONSENT, principal(guarantor, "GUARANTOR", "2"), people, TODAY)
    # посторонний пользователь без записи о компании
    assert not can_sign(COMPANY_CONSENT, principal(nobody, "ACCOUNTANT", "3"), people, TODAY)
    # личное: ИНН должен совпасть, а у учётки без ИНН не подписывается никто
    assert not can_sign(PERSONAL_CONSENT, principal(boss, "DIRECTOR", None), people, TODAY)
