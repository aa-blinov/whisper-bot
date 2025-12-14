import logging
import os
import shutil

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
DOWNLOAD_ROOT = "./data/whisper_models"

# Создаем директорию для моделей, если её нет
os.makedirs(DOWNLOAD_ROOT, exist_ok=True)

# Подавляем предупреждения о правах доступа от huggingface_hub
# Эти предупреждения не критичны и возникают из-за особенностей работы с временными файлами
os.environ["HF_HUB_DISABLE_EXPERIMENTAL_WARNING"] = "1"

# Устанавливаем HF_TOKEN для аутентификации в Hugging Face Hub (если указан)
# huggingface_hub поддерживает оба варианта имени переменной
HF_TOKEN = os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN")
if HF_TOKEN:
    os.environ["HF_TOKEN"] = HF_TOKEN
    os.environ["HUGGING_FACE_HUB_TOKEN"] = HF_TOKEN
    logger.info("HF_TOKEN установлен для аутентификации в Hugging Face Hub")
else:
    logger.info("HF_TOKEN не установлен. Будут использоваться неаутентифицированные запросы к HF Hub.")

model = None


def _load_model() -> bool:
    """Загрузить модель Whisper. Возвращает True при успехе, False при ошибке."""
    global model
    try:
        # Убеждаемся, что директория существует перед загрузкой
        os.makedirs(DOWNLOAD_ROOT, exist_ok=True)
        
        logger.info(
            f"Загрузка модели Faster-Whisper '{WHISPER_MODEL}' с compute_type='{COMPUTE_TYPE}'..."
        )
        model = WhisperModel(
            WHISPER_MODEL,
            device="cpu",
            compute_type=COMPUTE_TYPE,
            download_root=DOWNLOAD_ROOT,
            cpu_threads=CPU_THREADS,
            num_workers=NUM_WORKERS,
        )
        logger.info(f"Модель Faster-Whisper '{WHISPER_MODEL}' успешно загружена.")
        return True
    except Exception as e:
        # Проверяем, является ли ошибка связанной с поврежденной моделью
        error_str = str(e)
        if "parse error" in error_str or "json.exception" in error_str or "No such file or directory" in error_str:
            logger.warning(f"Обнаружена ошибка загрузки модели (возможно повреждена): {e}")
        else:
            logger.exception(f"Ошибка загрузки модели Faster-Whisper: {e}")
        model = None
        return False


def _remove_corrupted_model() -> None:
    """Удалить поврежденную модель для перезагрузки."""
    import time
    try:
        # Ищем директорию модели в download_root
        # faster-whisper использует формат: models--Systran--faster-whisper-{model_name}
        model_path = os.path.join(DOWNLOAD_ROOT, f"models--Systran--faster-whisper-{WHISPER_MODEL}")
        
        # Пробуем несколько раз удалить, так как другой процесс может использовать файлы
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if os.path.exists(model_path):
                    logger.warning(f"Удаление поврежденной модели (попытка {attempt + 1}/{max_retries}): {model_path}")
                    # Удаляем всю директорию модели
                    shutil.rmtree(model_path, ignore_errors=True)
                    # Даем время другим процессам завершить работу
                    time.sleep(0.5)
                    if not os.path.exists(model_path):
                        logger.info(f"Поврежденная модель успешно удалена: {model_path}")
                        break
                else:
                    # Пробуем найти любую директорию с именем модели
                    if os.path.exists(DOWNLOAD_ROOT):
                        for item in os.listdir(DOWNLOAD_ROOT):
                            item_path = os.path.join(DOWNLOAD_ROOT, item)
                            if os.path.isdir(item_path) and WHISPER_MODEL in item:
                                logger.warning(f"Удаление возможной поврежденной модели: {item_path}")
                                shutil.rmtree(item_path, ignore_errors=True)
                                time.sleep(0.5)
                                if not os.path.exists(item_path):
                                    logger.info(f"Директория удалена: {item_path}")
                                    break
                    break
            except (OSError, PermissionError) as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Не удалось удалить модель (попытка {attempt + 1}), повтор через 1 секунду: {e}")
                    time.sleep(1)
                else:
                    logger.error(f"Не удалось удалить поврежденную модель после {max_retries} попыток: {e}")
    except Exception as e:
        logger.warning(f"Ошибка при удалении поврежденной модели: {e}")


# Попытка загрузить модель при импорте
if not _load_model():
    # Если не удалось загрузить, возможно модель повреждена - удаляем и пробуем снова
    logger.warning("Попытка удалить поврежденную модель и перезагрузить...")
    _remove_corrupted_model()
    _load_model()


def transcribe_audio(audio_path: str, language: str = "ru") -> tuple[str | None, str | None]:
    logger.info(f"Начало transcribe_audio для файла: {audio_path}")
    global model
    if model is None:
        logger.warning("Модель Whisper не загружена. Попытка перезагрузки...")
        if not _load_model():
            logger.error("Модель Whisper не загружена. Невозможно выполнить транскрибацию.")
            return None, None
    try:
        logger.info(f"Начало транскрибации файла: {audio_path}")
        beam_size = int(BEAM_SIZE)
        segments, info = model.transcribe(audio_path, language=language, beam_size=beam_size)

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
        # Удаляем временный файл сразу после обработки
        if temp_audio_file and os.path.exists(temp_audio_file):
            try:
                os.remove(temp_audio_file)
                logger.info(f"Временный аудиофайл удален: {temp_audio_file}")
            except Exception as e:
                logger.warning(f"Не удалось удалить временный файл {temp_audio_file}: {e}")
        return text, lang
    finally:
        # Дополнительная проверка на случай, если файл не был удален выше
        if temp_audio_file and os.path.exists(temp_audio_file):
            try:
                os.remove(temp_audio_file)
                logger.info(f"Временный аудиофайл удален в finally: {temp_audio_file}")
            except Exception as e:
                logger.warning(f"Не удалось удалить временный файл {temp_audio_file} в finally: {e}")
