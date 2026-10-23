"""Upload rate is scoped to an authenticated session, not cleared by resetting a company."""

from redis import RedisError

from app.shared.cache import get_redis
from app.shared.errors import AppError
from app.shared.settings import get_settings

_COUNT = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], 60) end
return {n, redis.call('TTL', KEYS[1])}
"""


def check_upload_limit(session_key: str) -> None:
    if not get_settings().rate_limit_enabled:
        return
    try:
        count, ttl = get_redis().eval(_COUNT, 1, "scc:document-upload-rate:" + session_key)
    except RedisError as exc:
        raise AppError(503, "DEPENDENCY_UNAVAILABLE", "Загрузка временно недоступна") from exc
    if int(count) > 10:
        raise AppError(429, "RATE_LIMITED", headers={"Retry-After": str(max(1, int(ttl)))})
