"""Распознавание речи на ONNX-моделях.

Основная модель — GigaAM v3 (e2e CTC, Sber) в ONNX-сборке. Она отдаёт уже
готовый текст: с пунктуацией и заглавными буквами, поэтому отдельный
пунктуатор не нужен. Английский распознаётся второй моделью (Whisper),
она загружается только когда её действительно попросили.

Ни Torch, ни CTranslate2, ни faster-whisper здесь нет: одна ONNX-сессия
на процесс, декодирование звука через soundfile/ffmpeg.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading

import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
# GigaAM обучена на окнах до 30 с; 25 с оставляют запас и не режут речь
# посреди фразы, потому что точку разреза ищем в самом тихом месте.
CHUNK_SAMPLES = 25 * SAMPLE_RATE
CUT_SEARCH_SAMPLES = 2 * SAMPLE_RATE
CUT_FRAME_SAMPLES = 1_600
# Короткий буфер дополняем тишиной: свёрточный энкодер иначе падает на
# входе короче первого окна.
MIN_MODEL_SAMPLES = 8_000
MIN_RETRY_SAMPLES = 4_000

_lock = threading.Lock()
_models: dict[str, object] = {}


def _model_id(language: str) -> tuple[str, bool]:
    """Какую модель грузить для языка и нужно ли передавать ей язык.

    GigaAM понимает только русский и не принимает аргумент языка;
    Whisper — многоязычная, ей язык передаём.
    """
    from config import settings

    if (language or "ru").lower().startswith("en"):
        return settings.asr_model_en, True
    return settings.asr_model, False


def _load_model(model_id: str):
    """Загрузить ONNX-модель (один раз на процесс)."""
    with _lock:
        cached = _models.get(model_id)
        if cached is not None:
            return cached
        try:
            import onnx_asr
        except ImportError as exc:  # pragma: no cover - срабатывает только без зависимости
            raise RuntimeError(
                "Не установлен onnx-asr. Установите: pip install 'onnx-asr[hub,cpu]'"
            ) from exc

        from config import settings

        logger.info(
            "Загрузка ONNX-модели '%s' (quantization=%s)", model_id, settings.asr_quantization
        )
        model = onnx_asr.load_model(
            model_id,
            quantization=settings.asr_quantization or None,
            providers=["CPUExecutionProvider"],
        )
        _models[model_id] = model
        logger.info("Модель '%s' загружена", model_id)
        return model


def warm_up(language: str = "ru") -> None:
    """Загрузить модель заранее, чтобы первый запрос не ждал диск.

    Пустой звук — самый дешёвый способ получить рабочую ONNX-сессию и
    заодно убедиться, что модель действительно считает, а не только
    открылась.
    """
    model_id, needs_language = _model_id(language)
    try:
        model = _load_model(model_id)
        probe = np.zeros(SAMPLE_RATE // 2, dtype=np.float32)
        kwargs = {"language": "ru"} if needs_language else {}
        model.recognize(probe, **kwargs)
        logger.info("Модель '%s' прогрев прошла", model_id)
    except Exception as exc:  # прогрев не должен ронять контейнер
        logger.warning("Прогрев модели '%s' не удался: %s", model_id, exc)


def _resample(buf: np.ndarray, source_rate: int, target_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Линейная передискретизация — качества хватает, зависимостей нет."""
    if source_rate == target_rate or buf.size == 0:
        return buf
    duration = buf.size / float(source_rate)
    target_size = int(round(duration * target_rate))
    if target_size <= 0:
        return np.zeros(0, dtype=np.float32)
    x_old = np.linspace(0.0, duration, num=buf.size, endpoint=False)
    x_new = np.linspace(0.0, duration, num=target_size, endpoint=False)
    return np.interp(x_new, x_old, buf).astype(np.float32)


def _decode_with_soundfile(path: str) -> np.ndarray | None:
    try:
        import soundfile as sf
    except ImportError:
        return None
    try:
        buf, rate = sf.read(path, dtype="float32", always_2d=False)
    except Exception as exc:
        logger.debug("soundfile не смог прочитать %s: %s", path, exc)
        return None
    buf = np.asarray(buf, dtype=np.float32)
    if buf.ndim > 1:
        buf = buf.mean(axis=-1)
    return _resample(buf, int(rate))


def _decode_with_ffmpeg(path: str) -> np.ndarray | None:
    """ffmpeg декодирует всё, что прислал Telegram: OGG/Opus и MP4-кружок."""
    executable = shutil.which("ffmpeg")
    if executable is None:
        return None
    command = [
        executable,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "pipe:1",
    ]
    try:
        completed = subprocess.run(command, capture_output=True, check=False, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("ffmpeg не запустился: %s", exc)
        return None
    if completed.returncode != 0:
        logger.warning(
            "ffmpeg вернул код %s: %s",
            completed.returncode,
            completed.stderr.decode("utf-8", "replace").strip()[:400],
        )
        return None
    return np.frombuffer(completed.stdout, dtype=np.float32).copy()


def decode_audio(path: str) -> np.ndarray | None:
    """Декодировать файл в моно float32 16 кГц."""
    buf = _decode_with_soundfile(path)
    if buf is None:
        buf = _decode_with_ffmpeg(path)
    if buf is None:
        logger.error("Не удалось декодировать аудио: %s", path)
        return None
    if buf.size == 0:
        logger.warning("Файл не содержит звука: %s", path)
    return buf


def _extract_text(result) -> str | None:
    """Достать текст из ответа onnx-asr (строка или объект с .text)."""
    if result is None:
        return None
    if isinstance(result, str):
        return result.strip() or None
    text = getattr(result, "text", None)
    if isinstance(text, str):
        return text.strip() or None
    logger.error("Неожиданный ответ модели: %s", type(result).__name__)
    return None


def _cut_point(buf: np.ndarray, start: int, limit: int) -> int:
    """Конец куска: не дальше `limit`, но в самом тихом месте рядом с ним."""
    end = start + limit
    if end >= len(buf):
        return len(buf)
    low = max(start + limit // 2, end - CUT_SEARCH_SAMPLES)
    frames = (end - low) // CUT_FRAME_SAMPLES
    if frames < 2:
        return end
    segment = buf[low : low + frames * CUT_FRAME_SAMPLES].reshape(frames, -1)
    energy = np.abs(segment).mean(axis=1)
    # При равной энергии берём самый поздний кадр — ровный звук режется ровно.
    best = int(len(energy) - 1 - np.argmin(energy[::-1]))
    return low + (best + 1) * CUT_FRAME_SAMPLES


def _transcribe_chunk(model, chunk: np.ndarray, kwargs: dict) -> str | None:
    try:
        return _extract_text(model.recognize(chunk, **kwargs))
    except Exception:
        if len(chunk) <= MIN_RETRY_SAMPLES:
            raise
        logger.warning("Модель отклонила кусок %.1f с, делю пополам", len(chunk) / SAMPLE_RATE)
        middle = len(chunk) // 2
        parts = [
            text
            for text in (
                _transcribe_chunk(model, chunk[:middle], kwargs),
                _transcribe_chunk(model, chunk[middle:], kwargs),
            )
            if text
        ]
        return " ".join(parts) or None


def _transcribe_chunked(model, buf: np.ndarray, kwargs: dict) -> str | None:
    """Прогнать запись кусками до 25 с и склеить результат пробелом."""
    if len(buf) < MIN_MODEL_SAMPLES:
        buf = np.pad(buf, (0, MIN_MODEL_SAMPLES - len(buf)))
    if len(buf) <= CHUNK_SAMPLES:
        return _transcribe_chunk(model, buf, kwargs)

    parts: list[str] = []
    start = 0
    while start < len(buf):
        end = _cut_point(buf, start, CHUNK_SAMPLES)
        text = _transcribe_chunk(model, buf[start:end], kwargs)
        if text:
            parts.append(text)
        start = end
    return " ".join(parts) or None


def transcribe_audio(audio: np.ndarray, language: str = "ru") -> tuple[str | None, str | None]:
    """Распознать готовый буфер 16 кГц."""
    model_id, needs_language = _model_id(language)
    language_code = (language or "ru").lower()
    if language_code not in ("ru", "en"):
        language_code = "ru"
    try:
        model = _load_model(model_id)
        kwargs = {"language": language_code} if needs_language else {}
        text = _transcribe_chunked(model, np.asarray(audio, dtype=np.float32), kwargs)
        logger.info("Распознано %s символов (%s)", len(text or ""), model_id)
        return text, language_code
    except Exception:
        logger.exception("Ошибка распознавания (%s)", model_id)
        return None, None


def transcribe_media_sync(
    file_path: str, file_type: str, language: str = "ru"
) -> tuple[str | None, str | None]:
    """Декодировать файл из Telegram и распознать его.

    Отдельного шага «достать звук из кружка» больше нет: ffmpeg сам
    вытаскивает дорожку из MP4, поэтому голосовое и видео-кружок идут
    одним путём.
    """
    logger.info("Распознавание файла %s (тип %s, язык %s)", file_path, file_type, language)
    audio = decode_audio(file_path)
    if audio is None:
        return None, None
    return transcribe_audio(audio, language=language)


def model_info() -> str:
    """Короткое описание модели для логов и `/stats`."""
    from config import settings

    return f"{settings.asr_model} ({settings.asr_quantization or 'fp32'}, ONNX)"
