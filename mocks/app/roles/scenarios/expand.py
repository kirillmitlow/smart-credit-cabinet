"""Чистое разворачивание: пресет → явные параметры → детерминированные части моков.

Реквизиты (T-120) и финансы (T-121); кредитная история добавляется T-123…T-125.
Ни запросов к другим мокам, ни записи в базу здесь нет.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

from app.common.admin import merge_patch
from app.roles.scenarios.config import ScenarioSettings
from app.roles.scenarios.finance import expand_finance
from app.roles.scenarios.identity import expand_identity
from app.roles.scenarios.presets import PRESETS
from app.roles.scenarios.schemas import ScenarioSpec


def resolved_spec(spec: ScenarioSpec) -> ScenarioSpec:
    raw = spec.model_dump(mode="json", by_alias=True, exclude_unset=True)
    defaults = PRESETS[spec.preset][1] if spec.preset else {}
    merged = merge_patch(defaults, raw)
    # Абсолютная дата заменяет возраст из пресета, а не складывается с ним.
    if spec.company and spec.company.registration_date is not None:
        merged["company"].pop("ageMonths", None)
    return ScenarioSpec.model_validate(merged)


def preview_code(spec: ScenarioSpec) -> str:
    if spec.code:
        return spec.code
    raw = spec.model_dump(mode="json", by_alias=True, exclude_none=True)
    digest = hashlib.sha256(
        json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return "preview-" + digest[:20]


def expand(
    spec: ScenarioSpec,
    today: date,
    reserved_inns: set[str] | None = None,
    *,
    settings: ScenarioSettings | None = None,
) -> dict[str, Any]:
    code = preview_code(spec)
    resolved = resolved_spec(spec)
    expanded = expand_identity(resolved, code, today, reserved_inns or set())
    expanded.update(expand_finance(resolved, expanded["identity"], code, today, settings))
    return expanded
