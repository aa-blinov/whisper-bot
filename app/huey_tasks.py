"""Задача распознавания, которую бот ставит в очередь.

`stt_processor` импортируется внутри функции намеренно: бот импортирует
этот модуль ради `transcribe_task`, и если бы ONNX-модель грузилась на
уровне модуля, её копия висела бы в памяти и у бота, и у воркера.
"""

from __future__ import annotations

import logging
import os

from tasks import huey

logger = logging.getLogger(__name__)


def _remove(path: str | None) -> None:
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
            logger.info("Файл удалён: %s", path)
    except OSError as exc:
        logger.warning("Не удалось удалить файл %s: %s", path, exc)


@huey.task()
def transcribe_task(file_path: str, file_type: str, language: str = "ru"):
    """Распознать файл и удалить его с диска в любом исходе."""
    from stt_processor import transcribe_media_sync

    try:
        return transcribe_media_sync(file_path, file_type, language=language)
    except Exception:
        logger.exception("Ошибка обработки файла %s", file_path)
        raise
    finally:
        _remove(file_path)
        # Видео-кружок раньше превращался в отдельный mp3; на всякий случай
        # подчищаем и его, если файл остался от прошлых версий.
        _remove(file_path + ".mp3")


def warm_up() -> None:
    """Прогреть модель в воркере до первого запроса."""
    from stt_processor import warm_up as _warm_up

    _warm_up()
