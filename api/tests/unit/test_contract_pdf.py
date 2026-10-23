"""The saved PDF contains the accepted amounts, the full schedule, Cyrillic and the demo notice."""

import io
import json
import re
from decimal import Decimal

import pytest
from pypdf import PdfReader

from app.modules.documents.pdf import NOTICE, render_credit
from app.modules.offers.terms import loan_terms

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("schedule_only", [False, True])
def test_credit_pdf_uses_accepted_schedule(schedule_only: bool) -> None:
    terms = loan_terms("EXPRESS", 500_000, Decimal("0.215"), 12)
    body = {
        "bank": "Демо-банк",
        "borrower": {"name": "ИП Соколова Анна", "inn": "001234567887"},
        "product": {"title": "Экспресс-кредит"},
        "number": "КД-2026-000001",
        "applicationNumber": "АЗ-2026-000001",
        "contractUid": "test-uid",
        "amountRub": 500_000,
        "termMonths": 12,
        "ratePercent": "21.5",
        "paymentRub": terms.payment_rub,
        "lastPaymentRub": terms.last_payment_rub,
        "overpaymentRub": terms.overpayment_rub,
        "schedule": [
            {
                "number": r.number,
                "paymentRub": r.payment,
                "principalRub": r.principal,
                "interestRub": r.interest,
                "balanceRub": r.balance,
            }
            for r in terms.schedule
        ],
    }
    pdf = PdfReader(
        io.BytesIO(render_credit(json.dumps(body, ensure_ascii=False), schedule_only=schedule_only))
    )
    text = "".join(p.extract_text() for p in pdf.pages)
    compact = re.sub(r"\s", "", text)
    assert "Соколова" in text
    assert "001234567887" in text
    assert "КД-2026-000001" in text
    assert "500000₽" in compact
    assert "21.5%" in compact
    for row in terms.schedule:
        assert str(row.payment) + "₽" in compact
        assert str(row.balance) + "₽" in compact
    assert all(NOTICE in page.extract_text() for page in pdf.pages)


@pytest.mark.parametrize(
    ("field", "value"), [("amountRub", 900_000), ("termMonths", 24), ("ratePercent", "30")]
)
def test_variant_must_match_saved_terms(field: str, value: object) -> None:
    from app.modules.offers.contracts import verify_variant
    from app.modules.offers.models import Contract, OfferVariant
    from app.shared.errors import AppError

    body = {
        "product": {"code": "EXPRESS"},
        "amountRub": 500_000,
        "termMonths": 12,
        "ratePercent": "21.5",
        "contractUid": "uid",
        "number": "КД-1",
    }
    contract = Contract(body=json.dumps(body), contract_uid="uid", number="КД-1")
    variant = OfferVariant(
        product_code="EXPRESS", amount_rub=500_000, term_months=12, rate_percent=Decimal("21.5")
    )
    verify_variant(contract, variant)
    body[field] = value
    contract.body = json.dumps(body)
    with pytest.raises(AppError, match="Условия"):
        verify_variant(contract, variant)
