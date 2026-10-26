import json
import logging

from app.config import settings

logger = logging.getLogger("credit-cabinet")

_client = None
_disabled = False


def _client_or_none():
    global _client, _disabled
    if _disabled or not settings.redis_url:
        return None
    if _client is None:
        try:
            from redis import Redis

            client = Redis.from_url(
                settings.redis_url,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
                decode_responses=True,
            )
            client.ping()
            _client = client
        except Exception:
            logger.warning("redis unavailable, product cache disabled")
            _disabled = True
            return None
    return _client


def cache_get(key: str):
    client = _client_or_none()
    if client is None:
        return None
    try:
        raw = client.get(key)
    except Exception:
        logger.warning("redis read failed")
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def cache_set(key: str, value, ttl_seconds: int = 60) -> None:
    client = _client_or_none()
    if client is None:
        return
    try:
        client.set(key, json.dumps(value, ensure_ascii=False), ex=ttl_seconds)
    except Exception:
        logger.warning("redis write failed")


def redis_ready() -> bool:
    client = _client_or_none()
    if client is None:
        return False
    try:
        return bool(client.ping())
    except Exception:
        return False
