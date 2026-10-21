"""Базовые модели ответов: camelCase, блок meta бизнес-API, problem+json (разделы 2.1, 2.2, 2.4)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from fastapi import Request
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


Source = Literal[
    "EGRUL",
    "EGRIP",
    "FEDRESURS",
    "FNS_TRANSPARENT_BUSINESS",
    "FNS_GIR_BO",
    "FNS_RMSP",
    "FNS_BLOCKS",
    "EIS",
    "CREDIT_BUREAU",
    "BANK_CORE",
    "COMPLIANCE",
]


class Meta(CamelModel):
    source: Source
    simulated: Literal[True] = True
    request_id: str
    retrieved_at: datetime
    data_actual_at: date | None = None


def build_meta(request: Request, source: Source, data_actual_at: date | None = None) -> Meta:
    """Блок meta для ответа бизнес-API: requestId из запроса, время — по часам стенда."""
    return Meta(
        source=source,
        request_id=request.state.request_id,
        retrieved_at=request.app.state.clock.now().replace(microsecond=0),
        data_actual_at=data_actual_at,
    )


class Problem(CamelModel):
    type: str
    title: str
    status: int
    code: str
    detail: str | None = None
    request_id: str | None = None
    errors: list[dict[str, Any]] | None = None


# Описание кодов ошибок для `responses=` в роутерах: в /docs видны все ответы
def problem_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    return {s: {"model": Problem, "content": {"application/problem+json": {}}} for s in statuses}
