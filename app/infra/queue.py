"""Очередь Huey между ботом и воркером.

Задача импортирует распознавание внутри функции: бот импортирует этот
модуль ради `transcribe_task`, и если бы ONNX-модель грузилась на уровне
модуля, её копия висела бы в памяти и у бота, и у воркера.
"""

from __future__ import annotations

import logging

from huey import RedisExpireHuey

from app.config import Settings
from app.infra.media import MediaStorage

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
def transcribe_task(file_path: str, file_type: str, language: str = "ru"):
    """Распознать файл и удалить его с диска в любом исходе."""
    from app.infra.asr import Recognizer  # ленивый импорт: модель грузит только воркер
    from app.config import Settings as _Settings

    settings = _Settings.from_env()
    recognizer = Recognizer(
        settings.asr_model,
        settings.asr_model_en,
        settings.asr_quantization,
        settings.asr_threads,
    )
    try:
        return recognizer.transcribe_file(file_path, language=language)
    except Exception:
        logger.exception("Ошибка обработки файла %s", file_path)
        raise
    finally:
        storage = MediaStorage(settings.data_dir)
        storage.remove(file_path)
        # Видео-кружок раньше превращался в отдельный mp3; подчищаем и его,
        # если файл остался от прошлых версий.
        storage.remove(file_path + ".mp3")
