"""Очередь Huey между ботом и воркером.

Задача импортирует распознавание внутри функции: бот импортирует этот
модуль ради `transcribe_task`, и если бы ONNX-модель грузилась на уровне
модуля, её копия висела бы в памяти и у бота, и у воркера.
"""

from __future__ import annotations

import logging

from huey import RedisHuey

from app.config import Settings
from app.infra.media import MediaStorage

logger = logging.getLogger(__name__)

_settings = Settings.from_env()

huey = RedisHuey(
    "whisper-bot",
    host=_settings.redis_host,
    port=_settings.redis_port,
    db=_settings.redis_db,
    results=True,
)


@huey.task()
def transcribe_task(file_path: str, file_type: str, language: str = "ru"):
    """Распознать файл и удалить его с диска в любом исходе."""
    from app.infra.asr import Recognizer  # ленивый импорт: модель грузит только воркер
    from app.config import Settings as _Settings

    settings = _Settings.from_env()
    recognizer = Recognizer(
        settings.asr_model, settings.asr_model_en, settings.asr_quantization
    )
    try:
        return recognizer.transcribe_file(file_path, language=language)
    except Exception:
        logger.exception("Ошибка обработки файла %s", file_path)
        raise
    finally:
        MediaStorage(settings.data_dir).remove(file_path)
        # Видео-кружок раньше превращался в отдельный mp3; подчищаем и его,
        # если файл остался от прошлых версий.
        MediaStorage(settings.data_dir).remove(file_path + ".mp3")
