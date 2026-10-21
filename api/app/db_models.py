"""Все модели SQLAlchemy одним импортом: для Alembic и теста владения таблицами."""

import app.modules.audit.models
import app.modules.auth.models
import app.modules.companies.models
import app.shared.models  # noqa: F401
