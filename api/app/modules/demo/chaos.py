"""Прокси сбоев четырёх источников без раскрытия admin API/ключей."""

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal

from pydantic import Field, ValidationError

from app.modules.demo.catalog import Camel
from app.modules.integrations import System, chaos
from app.shared import operations
from app.shared.errors import AppError

Mode = Literal["OK", "SLOW", "ERROR", "DOWN", "LOST_RESPONSE"]


class ChaosInput(Camel):
    mode: Mode
    latency_ms: int | None = Field(default=None, ge=0, le=120_000)


class ChaosView(Camel):
    system: System
    available: bool
    mode: str | None = None
    latency_ms: int | None = None


def _view(system: System, data: dict[str, Any]) -> ChaosView:
    return ChaosView(
        system=system, available=True, mode=data["mode"], latency_ms=data.get("latencyMs")
    )


def _get(system: System) -> ChaosView:
    try:
        return _view(system, chaos.configure(system))
    except (chaos.ChaosUnavailableError, ValidationError, KeyError):
        return ChaosView(system=system, available=False)


def list_chaos() -> list[ChaosView]:
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(_get, System))


def set_chaos(system: System, body: ChaosInput) -> ChaosView:
    try:
        with operations.hold(lambda: None):
            return _view(
                system,
                chaos.configure(
                    system,
                    {
                        "mode": body.mode,
                        "latencyMs": body.latency_ms,
                        "errorRate": 1.0,
                        "paths": None,
                        "rateLimitPerMinute": None,
                        "until": None,
                    },
                ),
            )
    except (chaos.ChaosUnavailableError, ValidationError, KeyError) as exc:
        raise AppError(502, "DEMO_CHAOS_UNAVAILABLE") from exc
