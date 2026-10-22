"""Не больше 30 обращений к автозаполнению за минуту на сессию (50-09, T-220)."""

from redis import RedisError

from app.modules import auth
from app.shared.cache import get_redis
from app.shared.errors import AppError
from app.shared.settings import get_settings

KEY_PREFIX = "scc:company-profile-rate:"
_COUNT = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], 60) end
return {n, redis.call('TTL', KEYS[1])}
"""


def check_limit(principal: auth.Principal) -> None:
    if not get_settings().rate_limit_enabled:
        return
    try:
        result = get_redis().eval(
            _COUNT, 1, KEY_PREFIX + (principal.session_id or str(principal.user_id))
        )
        count, ttl = result
    except RedisError as exc:
        raise AppError(
            503, "DEPENDENCY_UNAVAILABLE", "Счётчик обращений временно недоступен"
        ) from exc
    if int(count) > 30:
        raise AppError(429, "RATE_LIMITED", headers={"Retry-After": str(max(1, int(ttl)))})
