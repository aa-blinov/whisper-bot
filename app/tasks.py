"""Экземпляр Huey: очередь между ботом и воркером.

Адрес Redis берётся из окружения, поэтому контейнеры можно переставить
или запустить рядом с чужим Redis, не правя код.
"""

from huey import RedisHuey

from config import settings

huey = RedisHuey(
    "whisper-bot",
    host=settings.redis_host,
    port=settings.redis_port,
    db=settings.redis_db,
    results=True,
)
