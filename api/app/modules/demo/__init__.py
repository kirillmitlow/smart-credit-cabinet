"""Сброс стенда, сбои моков, список персон; только при DEMO_MODE. Документ: 60-05, D-081.

Персоны и сбои читаются через публичные адаптеры; сбросы вызывают зарегистрированных владельцев.
Модули `api` demo не импортирует: они регистрируют свои сбросы в `app.shared.resets`.
"""

from app.modules.demo.router import require_demo_mode, router

__all__ = ["require_demo_mode", "router"]
