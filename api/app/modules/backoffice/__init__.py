"""Очередь ручного рассмотрения, карточка заявки, решение андеррайтера. Документ: 10-10, 60-04, D-010."""

from app.modules.backoffice.outbox_service import operation_scope as outbox_operation_scope
from app.modules.backoffice.router import router

__all__ = ["outbox_operation_scope", "router"]
