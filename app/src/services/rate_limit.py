import redis

from src.config import settings
from src.logging import logger

_redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """Получить (или создать) клиент Redis."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_dsn, decode_responses=True)
    return _redis_client


def can_send(user_id: int) -> bool:
    """
    Проверить, может ли пользователь отправить сообщение автору.

    Использует SET NX EX — атомарная проверка + установка TTL.
    Возвращает True, если лимит не исчерпан (ключ успешно установлен).
    """
    r = get_redis()
    key = f"rl:msg_to_author:{user_id}"
    result = r.set(key, "1", nx=True, ex=settings.rate_limit_seconds)
    if result:
        logger.info("Rate limit OK for user %d", user_id)
        return True
    else:
        ttl = r.ttl(key)
        logger.info("Rate limit HIT for user %d, ttl=%d", user_id, ttl)
        return False


def get_ttl(user_id: int) -> int:
    """Получить оставшееся время до сброса лимита (в секундах)."""
    r = get_redis()
    key = f"rl:msg_to_author:{user_id}"
    ttl = r.ttl(key)
    return max(ttl, 0)
