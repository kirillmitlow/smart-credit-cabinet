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
    assert "Соколова" in text and "001234567887" in text and "КД-2026-000001" in text
    assert "500000₽" in compact and "21.5%" in compact
    for row in terms.schedule:
        assert str(row.payment) + "₽" in compact
        assert str(row.balance) + "₽" in compact
    assert all(NOTICE in page.extract_text() for page in pdf.pages)
