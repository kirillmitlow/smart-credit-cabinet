"""Сброс стенда, сбои моков, список персон; только при DEMO_MODE. Документ: 60-05, D-081.

Сейчас здесь гейт `DEMO_MODE` и единый сброс (T-371); персоны и сбои — продолжение T-370.
Модули `api` demo не импортирует: они регистрируют свои сбросы в `app.shared.resets`.
"""

from app.modules.demo.router import require_demo_mode, router

__all__ = ["require_demo_mode", "router"]
