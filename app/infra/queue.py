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
def transcribe_task(source: str, file_type: str, language: str = "ru"):
    """Распознать файл по ссылке Telegram или по локальному пути.

    Ссылка живёт около часа и содержит токен бота, поэтому её нельзя
    логировать; в задаче она только передаётся в ffmpeg.
    """
    from app.config import Settings as _Settings
    from app.infra.asr import Recognizer  # ленивый импорт: модель грузит только воркер

    settings = _Settings.from_env()
    recognizer = Recognizer(
        settings.asr_model,
        settings.asr_model_en,
        settings.asr_quantization,
        settings.asr_threads,
    )
    return recognizer.transcribe_source(source, language=language)
