"""D-086/T-374: код и лимит облачных демо-операций; локально открыто."""

import hmac
from hashlib import sha256
from typing import Annotated

from fastapi import Header, Request
from redis.exceptions import RedisError

from app.shared import cache, clock
from app.shared.errors import AppError
from app.shared.settings import AppEnv, Settings


def require_control(
    request: Request,
    stand_code: Annotated[str | None, Header(alias="X-Demo-Code")] = None,
) -> None:
    settings: Settings = request.app.state.settings
    if settings.app_env is not AppEnv.CLOUD:
        return
    # Счётчик не входит в префиксы сброса: reset не восстанавливает квоту атакующему.
    bucket = int(clock.system_now().timestamp()) // 60
    address = request.client.host if request.client else "unknown"
    key = f"demo-control-rate:{sha256(address.encode()).hexdigest()}:{bucket}"
    try:
        with cache.get_redis().pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, 120)
            hits, _ = pipe.execute()
    except RedisError as exc:
        raise AppError(503, "DEMO_CONTROL_UNAVAILABLE") from exc
    if hits > settings.demo_controls_per_minute:
        raise AppError(429, "RATE_LIMITED", headers={"Retry-After": "60"})
    expected = settings.demo_stand_code.get_secret_value()
    if (
        not expected
        or not stand_code
        or len(stand_code) > 128
        or not hmac.compare_digest(stand_code.encode(), expected.encode())
    ):
        raise AppError(403, "DEMO_CODE_REQUIRED")
