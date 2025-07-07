import os

from tasks import huey

from stt_processor import transcribe_media_sync


@huey.task()
def transcribe_task(file_path: str, file_type: str, language: str = "ru"):
    try:
        result = transcribe_media_sync(file_path, file_type, language=language)
        return result
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
