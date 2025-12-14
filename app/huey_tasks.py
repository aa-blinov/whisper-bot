import logging
import os

from tasks import huey

from stt_processor import transcribe_media_sync

logger = logging.getLogger(__name__)


@huey.task()
def transcribe_task(file_path: str, file_type: str, language: str = "ru"):
    try:
        result = transcribe_media_sync(file_path, file_type, language=language)
        # Удаляем файл сразу после обработки, до возврата результата
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"Файл успешно удален после обработки: {file_path}")
            except Exception as e:
                logger.warning(f"Не удалось удалить файл {file_path}: {e}")
        return result
    except Exception as e:
        logger.exception(f"Ошибка при обработке файла {file_path}: {e}")
        # Удаляем файл даже при ошибке
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"Файл удален после ошибки: {file_path}")
            except Exception as remove_error:
                logger.warning(f"Не удалось удалить файл {file_path} после ошибки: {remove_error}")
        raise
