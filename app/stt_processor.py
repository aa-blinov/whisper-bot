import logging
import os

from dotenv import load_dotenv

from faster_whisper import WhisperModel
from pydub import AudioSegment

logger = logging.getLogger(__name__)

load_dotenv()
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
BEAM_SIZE = os.getenv("WHISPER_BEAM_SIZE", "5")
CPU_THREADS = int(os.getenv("WHISPER_CPU_THREADS", "10"))
NUM_WORKERS = int(os.getenv("WHISPER_NUM_WORKERS", "1"))

try:
    logger.info(
        f"Загрузка модели Faster-Whisper '{WHISPER_MODEL}' с compute_type='{COMPUTE_TYPE}'..."
    )
    model = WhisperModel(
        WHISPER_MODEL,
        device="cpu",
        compute_type=COMPUTE_TYPE,
        download_root="./data/whisper_models",
        cpu_threads=CPU_THREADS,
        num_workers=NUM_WORKERS,
    )
    logger.info(f"Модель Faster-Whisper '{WHISPER_MODEL}' успешно загружена.")
except Exception as e:
    logger.exception(f"Ошибка загрузки модели Faster-Whisper: {e}")
    model = None


def transcribe_audio(audio_path: str, language: str = "ru") -> tuple[str | None, str | None]:
    logger.info(f"Начало transcribe_audio для файла: {audio_path}")
    if model is None:
        logger.error("Модель Whisper не загружена. Невозможно выполнить транскрибацию.")
        return None, None
    try:
        logger.info(f"Начало транскрибации файла: {audio_path}")
        segments, info = model.transcribe(audio_path, language=language, beam_size=5)

        full_text = []
        for segment in segments:
            full_text.append(segment.text)

        text = " ".join(full_text).strip()
        lang = getattr(info, "language", None)
        logger.info(f"Транскрибация завершена. Текст: {text[:100]}... Язык: {lang}")
        return text, lang
    except Exception as e:
        logger.exception(f"Ошибка при транскрибации аудио: {e}")
        return None, None


def extract_audio_from_video(video_path: str, output_audio_path: str) -> bool:
    logger.info(f"Начало extract_audio_from_video для файла: {video_path}")
    try:
        logger.info(f"Извлечение аудио из видео: {video_path} в {output_audio_path}")
        video = AudioSegment.from_file(video_path)
        video.export(output_audio_path, format="mp3")
        logger.info("Аудио успешно извлечено.")
        return True
    except Exception as e:
        logger.exception(f"Ошибка при извлечении аудио из видео: {e}")
        return False


def transcribe_media_sync(file_path: str, file_type: str, language: str = "ru") -> tuple[str | None, str | None]:
    logger.info(
        f"Начало transcribe_media_sync для файла: {file_path}, тип: {file_type}, язык: {language}"
    )
    audio_to_transcribe_path = file_path
    temp_audio_file = None

    try:
        if file_type == "video_note":
            temp_audio_file = file_path + ".mp3"
            success = extract_audio_from_video(file_path, temp_audio_file)
            if not success:
                return None, None
            audio_to_transcribe_path = temp_audio_file

        text, lang = transcribe_audio(audio_to_transcribe_path, language=language)
        return text, lang
    finally:
        if temp_audio_file and os.path.exists(temp_audio_file):
            os.remove(temp_audio_file)
            logger.info(f"Временный аудиофайл удален: {temp_audio_file}")
