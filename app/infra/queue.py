"""Очередь Huey между ботом и воркером.

Задача импортирует распознавание внутри функции: бот импортирует этот
модуль ради `transcribe_task`, и если бы ONNX-модель грузилась на уровне
модуля, её копия висела бы в памяти и у бота, и у воркера.
"""

from __future__ import annotations

import logging

from huey import RedisExpireHuey

from app.config import Settings

logger = logging.getLogger(__name__)

_settings = Settings.from_env()

# RedisExpireHuey держит результат с TTL. Обычный RedisHuey пишет его в
# бессрочный hash: если бот не дождался ответа по таймауту, ключ остаётся
# в Redis навсегда. TTL закрывает эту утечку.
huey = RedisExpireHuey(
    "lazy-to-text-bot",
    host=_settings.redis_host,
    port=_settings.redis_port,
    db=_settings.redis_db,
    results=True,
    expire_time=_settings.result_ttl_seconds,
)


@huey.task()
def transcribe_task(
    source: str,
    file_type: str,
    language: str = "ru",
    progress_key: str = "",
    total_seconds: int = 0,
):
    """Распознать файл по ссылке Telegram или по локальному пути.

    Ссылка живёт около часа и содержит токен бота, поэтому её нельзя
    логировать; в задаче она только передаётся в ffmpeg.

    Пока идёт распознавание, воркер пишет в Redis пару
    `обработано:всего` секунд, чтобы бот мог показать прогресс.
    """
    import time

    import redis

    from app.config import Settings as _Settings
    from app.infra.asr import SAMPLE_RATE, Recognizer  # ленивый импорт: модель в воркере

    settings = _Settings.from_env()
    recognizer = Recognizer(
        settings.asr_model,
        settings.asr_model_en,
        settings.asr_quantization,
        settings.asr_threads,
    )

    client = None
    last_written = 0.0

    def report(processed: int, total: int) -> None:
        nonlocal client, last_written
        if not progress_key:
            return
        now = time.monotonic()
        if now - last_written < 2:
            return
        last_written = now
        try:
            if client is None:
                client = redis.Redis(
                    host=settings.redis_host,
                    port=settings.redis_port,
                    db=settings.redis_db,
                    socket_timeout=1,
                )
            client.setex(
                progress_key,
                300,
                f"{processed // SAMPLE_RATE}:{max(0, int(total_seconds))}",
            )
        except Exception:  # прогресс не должен ломать распознавание
            pass

    return recognizer.transcribe_source(
        source,
        language=language,
        max_seconds=settings.max_media_seconds,
        progress=report,
        total_seconds=total_seconds,
    )
