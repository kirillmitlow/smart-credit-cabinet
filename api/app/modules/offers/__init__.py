"""Предложение банка и варианты, принятие, договор, имитация простой подписи. Документ: 20-04, 30-10.

Публичный интерфейс модуля — только то, что ниже.
"""

from app.modules.offers.models import Contract, Offer, OfferVariant, Signature
from app.modules.offers.router import router
from app.modules.offers.schemas import OfferOut, Percent, VariantOut
from app.modules.offers.service import VariantDraft, create_offer, current_offer
from app.modules.offers.views import offer_out

__all__ = [
    "Contract",
    "Offer",
    "OfferOut",
    "OfferVariant",
    "Percent",
    "Signature",
    "VariantDraft",
    "VariantOut",
    "create_offer",
    "current_offer",
    "offer_out",
    "router",
]
