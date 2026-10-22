"""Все модели SQLAlchemy одним импортом: для Alembic и теста владения таблицами."""

import app.modules.applications.models
import app.modules.audit.models
import app.modules.auth.models
import app.modules.companies.models
import app.modules.disbursement.models
import app.modules.integrations.models
import app.modules.loans.models
import app.modules.pipeline.models
import app.shared.models  # noqa: F401
