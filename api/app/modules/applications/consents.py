"""Согласия заявки: набор, полномочия, подпись пакета одним кодом (T-260, T-261, 20-04, D-091, D-092).

Что нужно подписать, определяет заявка: по одному согласию на человека и вид. Согласие компании
подписывает руководитель или сотрудник с действующим SIGN_COMPANY_CONSENTS, личные — только сам
человек. Пакет одного человека подтверждается одним кодом цели SIGN_CONSENT; код привязан к
человеку и к точному составу пакета, в базе остаётся HMAC-доказательство, а не хеш кода.
Согласие принадлежит одной заявке и на новую не переносится (D-077).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules import audit, auth, catalog, companies
from app.modules.applications import consent_texts as texts
from app.modules.applications.consent_proof import SIGN_METHOD, SIGN_PURPOSE, proof_for
from app.modules.applications.models import Application, Consent
from app.modules.applications.service import record_event, register_submit_check
from app.modules.applications.states import TERMINAL, Actor, Status
from app.modules.decisioning import add_months
from app.shared import clock
from app.shared.errors import AppError, not_found

BANK_NAME = "Банк (демонстрационный)"
PURPOSE = "LOAN_APPLICATION"
PEP_ACCEPTED = "PEP_RULES_ACCEPTED"
_BUNDLE_NAMESPACE = uuid.UUID("5c3c6a52-8d0b-4c43-9b8e-6f5a3d7b1c11")

Key = tuple[str, str]  # (вид, ИНН субъекта)


@dataclass(frozen=True, slots=True)
class Required:
    """Одно обязательное согласие заявки."""

    kind: str  # BKI | TURNOVER | PERSONAL_DATA
    subject_inn: str
    subject_type: str  # COMPANY | PERSON
    role: str  # COMPANY | IP | DIRECTOR | OWNER | GUARANTOR
    name: str

    @property
    def key(self) -> Key:
        return (self.kind, self.subject_inn)


@dataclass(frozen=True, slots=True)
class SignedConsent:
    consent_id: str
    kind: str
    subject_inn: str
    subject_type: str
    role: str
    purpose: str
    text_version: str
    signed_at: datetime
    valid_until: date
    sign_method: str
    signer_inn: str | None


@dataclass(frozen=True, slots=True)
class SignedBkiConsent:
    """Что нужно конвейеру для запроса в БКИ; он собирает из этого `integrations.BkiConsent`."""

    consent_id: str
    subject_inn: str
    subject_kind: str  # COMPANY | PERSON
    role: str  # COMPANY | DIRECTOR | OWNER | GUARANTOR | IP
    signed_at: datetime
    valid_until: date
    purpose: str  # LOAN_APPLICATION
    # Остальное, что требует БКИ (credit_bureau.BkiConsent): метод, ИНН подписанта, версия текста
    sign_method: str = SIGN_METHOD
    signer_inn: str = ""
    text_version: str = ""


@dataclass(frozen=True, slots=True)
class ItemState:
    required: Required
    consent: Consent | None
    status: str  # PENDING | SIGNED | EXPIRED
    can_sign: bool


@dataclass(frozen=True, slots=True)
class Challenge:
    request_id: str
    expires_in: int
    code: str
    items: tuple[Required, ...]


def consent_id_of(consent: Consent) -> str:
    return "cns_" + consent.id.hex


# ---------------------------------------------------------------- набор согласий


def required_consents(
    session: Session, application: Application
) -> tuple[list[Required], list[companies.Person]]:
    """Набор обязательных согласий заявки и люди компании. Директор = владелец — одно согласие."""
    company = companies.by_id(session, application.company_id)
    if company is None:
        raise not_found("Компания")
    people = companies.people(session, company.id)
    bki: list[Required] = []
    turnover: list[Required] = []
    personal: list[Required] = []

    def add(bucket: list[Required], item: Required) -> None:
        if all(item.key != existing.key for existing in bucket):
            bucket.append(item)

    if company.kind == "IP":
        # ИП — человек: одно БКИ и одно ПДн на его личный ИНН (совпадает с ИНН ИП)
        add(bki, Required("BKI", company.inn, "PERSON", "IP", company.name))
        add(personal, Required("PERSONAL_DATA", company.inn, "PERSON", "IP", company.name))
    else:
        add(bki, Required("BKI", company.inn, "COMPANY", "COMPANY", company.name))
        director = next((p for p in people if p.role == "DIRECTOR"), None)
        humans = ([(director, "DIRECTOR")] if director else []) + [
            (p, "GUARANTOR") for p in people if p.role == "GUARANTOR"
        ]
        for person, role in humans:
            if person.person_inn:
                add(bki, Required("BKI", person.person_inn, "PERSON", role, person.display_name))
                add(
                    personal,
                    Required(
                        "PERSONAL_DATA", person.person_inn, "PERSON", role, person.display_name
                    ),
                )
    if company.is_bank_customer:
        add(turnover, Required("TURNOVER", company.inn, "COMPANY", "COMPANY", company.name))
    return [*bki, *turnover, *personal], people


def _active(session: Session, application_id: UUID) -> dict[Key, Consent]:
    rows = session.scalars(
        select(Consent).where(
            Consent.application_id == application_id, Consent.revoked_at.is_(None)
        )
    )
    return {(c.kind, c.subject_inn): c for c in rows}


def _status(consent: Consent | None, today: date) -> str:
    if consent is None:
        return "PENDING"
    return "EXPIRED" if consent.valid_until < today else "SIGNED"


def signer_identity(principal: auth.Principal) -> str:
    """Кто подписывает: личный ИНН, а при его отсутствии (тестовые учётки) — идентификатор."""
    return principal.person_inn or str(principal.user_id)


def can_sign(
    required: Required,
    principal: auth.Principal,
    people: Sequence[companies.Person],
    today: date,
) -> bool:
    if required.subject_type == "PERSON":
        return principal.person_inn is not None and principal.person_inn == required.subject_inn
    me = next((p for p in people if p.user_id == principal.user_id), None)
    return me is not None and companies.can_sign_company_consents(me, today)


def item_states(
    session: Session, principal: auth.Principal, application: Application
) -> list[ItemState]:
    required, people = required_consents(session, application)
    active = _active(session, application.id)
    today = clock.today()
    return [
        ItemState(
            r,
            active.get(r.key),
            _status(active.get(r.key), today),
            can_sign(r, principal, people, today),
        )
        for r in required
    ]


def visible_to(principal: auth.Principal, application: Application, state: ItemState) -> bool:
    """Поручитель видит только свои согласия (D-096); остальные участники — все."""
    member = principal.membership(application.company_id)
    if member is not None and member.role == "GUARANTOR":
        return (
            principal.person_inn is not None and principal.person_inn == state.required.subject_inn
        )
    return True


def render_text(application: Application, required: Required, text: texts.ConsentText) -> str:
    return text.render(
        name=required.name,
        inn=required.subject_inn,
        application_number=application.number,
        bank_name=BANK_NAME,
        months=str(catalog.get_policy().timing.consent_months.value),
    )


# ---------------------------------------------------------------- подпись пакета


def _ensure_open(application: Application) -> None:
    if Status(application.status) in TERMINAL:
        raise AppError(
            409,
            "INVALID_TRANSITION",
            "Заявка закрыта: согласия не принимаются",
            errors=[{"currentStatus": application.status}],
        )


def _resolve(required: Sequence[Required], refs: Iterable[Key]) -> list[Required]:
    by_key = {r.key: r for r in required}
    chosen: dict[Key, Required] = {}
    for ref in refs:
        item = by_key.get(ref)
        if item is None:
            raise AppError(
                422,
                "VALIDATION_ERROR",
                "Такого согласия нет в наборе заявки",
                errors=[{"loc": ["body", "items"], "msg": f"{ref[0]}: нет в наборе"}],
            )
        chosen[ref] = item
    return list(chosen.values())


def _authorize(
    chosen: Sequence[Required],
    principal: auth.Principal,
    people: Sequence[companies.Person],
    today: date,
) -> None:
    for item in chosen:
        if can_sign(item, principal, people, today):
            continue
        if item.subject_type == "PERSON":
            raise AppError(403, "SIGNER_MISMATCH", "Личное согласие подписывает только сам человек")
        raise AppError(
            403, "ROLE_CANNOT_SIGN", "Нужны полномочия руководителя или SIGN_COMPANY_CONSENTS"
        )


def bundle_fingerprint(application_id: UUID, refs: Iterable[Key]) -> str:
    """Состав пакета для привязки кода: тот же код не подпишет другой набор согласий."""
    keys = sorted(set(refs))
    payload = json.dumps([str(application_id), keys], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def pep_rules_version() -> str:
    return texts.pep_rules().key


def ensure_pep_rules(
    session: Session,
    principal: auth.Principal,
    application: Application,
    *,
    accepted: bool,
) -> str:
    """Правила простой подписи принимаются один раз на человека (аудит); возвращает версию правил.

    Общая для согласий и договора: «соглашение сторон» одно (20-04, 63-ФЗ ст. 9).
    """
    rules = texts.pep_rules()
    if not audit.exists(session, PEP_ACCEPTED, actor_id=principal.user_id):
        if not accepted:
            raise AppError(
                422,
                "PEP_RULES_NOT_ACCEPTED",
                "Нужно принять правила использования простой подписи",
            )
        audit.record(
            session,
            PEP_ACCEPTED,
            actor_id=principal.user_id,
            actor_role=principal.role,
            object_type="user",
            object_id=str(principal.user_id),
            company_id=application.company_id,
            details={"rulesVersion": rules.key},
        )
    return rules.key


def request_signing(
    session: Session,
    principal: auth.Principal,
    application: Application,
    refs: Sequence[Key],
    *,
    accept_pep_rules: bool,
) -> Challenge:
    """Шаг 1: галочки поставлены → проверить полномочия, принять правила подписи, выпустить код."""
    _ensure_open(application)
    required, people = required_consents(session, application)
    chosen = _resolve(required, refs)
    today = clock.today()
    _authorize(chosen, principal, people, today)
    active = _active(session, application.id)
    if all(_status(active.get(r.key), today) == "SIGNED" for r in chosen):
        raise AppError(409, "CONSENT_ALREADY_SIGNED", "Эти согласия уже подписаны")
    ensure_pep_rules(session, principal, application, accepted=accept_pep_rules)
    issued = auth.codes.issue(
        signer_identity(principal),
        SIGN_PURPOSE,
        bundle_fingerprint(application.id, (r.key for r in chosen)),
        company_id=application.company_id,
    )
    return Challenge(issued.request_id, issued.expires_in, issued.code, tuple(chosen))


def sign_bundle(
    session: Session,
    principal: auth.Principal,
    application: Application,
    request_id: str,
    code: str,
    refs: Sequence[Key],
) -> list[Consent]:
    """Шаг 2: верный код подписывает весь пакет; повтор того же запроса возвращает те же записи."""
    _ensure_open(application)
    bundle_id = uuid.uuid5(_BUNDLE_NAMESPACE, request_id)
    done = list(
        session.scalars(
            select(Consent).where(
                Consent.bundle_id == bundle_id, Consent.application_id == application.id
            )
        )
    )
    if done and all(c.signer_user_id == principal.user_id for c in done):
        return done  # двойное «Подписать»: второй подписи не создаём
    required, people = required_consents(session, application)
    chosen = _resolve(required, refs)
    today = clock.today()
    _authorize(chosen, principal, people, today)
    verified = auth.codes.verify(request_id, code, purpose=SIGN_PURPOSE)
    signer = signer_identity(principal)
    if verified.person_inn != signer or verified.subject != bundle_fingerprint(
        application.id, (r.key for r in chosen)
    ):
        raise AppError(403, "SIGNER_MISMATCH", "Код выдан другому человеку или на другой набор")

    now = clock.now()
    valid_until = add_months(today, catalog.get_policy().timing.consent_months.value)
    active = _active(session, application.id)
    created: list[Consent] = []
    for item in chosen:
        prior = active.get(item.key)
        if prior is not None:
            if _status(prior, today) == "SIGNED":
                continue
            prior.revoked_at = now  # просроченное заменяем новым согласием
            session.flush()
        text = texts.current_for_kind(item.kind)
        consent = Consent(
            application_id=application.id,
            bundle_id=bundle_id,
            subject_inn=item.subject_inn,
            subject_type=item.subject_type,
            role=item.role,
            kind=item.kind,
            purpose=PURPOSE,
            text_version=text.key,
            text_hash=text.sha256,
            signed_at=now,
            valid_until=valid_until,
            signer_user_id=principal.user_id,
            signer_inn=principal.person_inn,
            sign_method=SIGN_METHOD,
            proof=proof_for(
                code=code,
                text_hash=text.sha256,
                signer_inn=signer,
                attempt_id=request_id,
                subject_inn=item.subject_inn,
                kind=item.kind,
            ),
        )
        session.add(consent)
        created.append(consent)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        raise AppError(409, "CONSENT_ALREADY_SIGNED", "Эти согласия уже подписаны") from exc
    if created:
        record_event(
            session,
            application,
            "STEP",
            actor_type=Actor.CLIENT,
            actor_id=principal.user_id,
            step_code="CONSENT_SIGNED",
            payload={
                "bundleId": str(bundle_id),
                "kinds": sorted({c.kind for c in created}),
                "count": len(created),
            },
        )
    return created


# ---------------------------------------------------------------- проверки для других модулей


def _signed(consent: Consent) -> SignedConsent:
    return SignedConsent(
        consent_id=consent_id_of(consent),
        kind=consent.kind,
        subject_inn=consent.subject_inn,
        subject_type=consent.subject_type,
        role=consent.role,
        purpose=consent.purpose,
        text_version=consent.text_version,
        signed_at=consent.signed_at,
        valid_until=consent.valid_until,
        sign_method=consent.sign_method,
        signer_inn=consent.signer_inn,
    )


def get_valid_consent(
    session: Session,
    application_id: UUID,
    subject_inn: str,
    kind: str,
    *,
    on: date | None = None,
) -> SignedConsent:
    """Действующее согласие субъекта для этой заявки или `CONSENT_REQUIRED` / `CONSENT_EXPIRED`."""
    consent = _active(session, application_id).get((kind, subject_inn))
    if consent is None:
        raise AppError(422, "CONSENT_REQUIRED", "Нет подписанного согласия")
    if consent.valid_until < (on or clock.today()):
        raise AppError(422, "CONSENT_EXPIRED", "Срок согласия истёк")
    return _signed(consent)


_ROLE_ORDER = {"COMPANY": 0, "IP": 1, "DIRECTOR": 2, "OWNER": 3, "GUARANTOR": 4}


def bki_consents(session: Session, application_id: UUID) -> list[SignedBkiConsent]:
    """Подписанные и не отозванные согласия на запрос в БКИ по заявке (для конвейера).

    Срок не отсекаем: просроченное согласие адаптер БКИ отклонит сам (`CONSENT_EXPIRED`).
    """
    rows = session.scalars(
        select(Consent).where(
            Consent.application_id == application_id,
            Consent.kind == "BKI",
            Consent.revoked_at.is_(None),
        )
    )
    ordered = sorted(rows, key=lambda c: (_ROLE_ORDER.get(c.role, 9), c.signed_at, c.subject_inn))
    return [
        SignedBkiConsent(
            consent_id=consent_id_of(c),
            subject_inn=c.subject_inn,
            subject_kind=c.subject_type,
            role=c.role,
            signed_at=c.signed_at,
            valid_until=c.valid_until,
            purpose=c.purpose,
            sign_method=c.sign_method,
            signer_inn=c.signer_inn or c.subject_inn,
            text_version=c.text_version,
        )
        for c in ordered
    ]


def check_before_submit(
    session: Session, application: Application, principal: auth.Principal
) -> None:
    """Без всех обязательных согласий заявка не отправляется: 422 CONSENT_REQUIRED (20-04, D-090)."""
    required, _ = required_consents(session, application)
    active = _active(session, application.id)
    today = clock.today()
    missing = [r for r in required if r.key not in active]
    if missing:
        raise AppError(
            422,
            "CONSENT_REQUIRED",
            "Нужны подписанные согласия",
            errors=[{"kind": r.kind, "role": r.role} for r in missing],
        )
    expired = [r for r in required if _status(active.get(r.key), today) == "EXPIRED"]
    if expired:
        raise AppError(
            422,
            "CONSENT_EXPIRED",
            "Срок согласий истёк, подпишите заново",
            errors=[{"kind": r.kind, "role": r.role} for r in expired],
        )


register_submit_check(check_before_submit)
