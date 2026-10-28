"""Распознавание речи на ONNX-моделях.

Основная модель: GigaAM v3 (e2e CTC, Sber) в ONNX-сборке. Она отдаёт уже
готовый текст: с пунктуацией и заглавными буквами, поэтому отдельный
пунктуатор не нужен. Английский распознаётся второй моделью (Whisper),
она загружается только когда её действительно попросили.

Ни Torch, ни CTranslate2, ни faster-whisper здесь нет: одна ONNX-сессия
на процесс, декодирование звука через soundfile и ffmpeg.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
import threading
import time

import numpy as np

logger = logging.getLogger(__name__)

# Ссылка Telegram содержит токен бота. Её нельзя писать в логи, а ffmpeg
# охотно повторяет её в stderr, поэтому любую ссылку заменяем заглушкой.
_URL_RE = re.compile(r"https?://\S+")


def _scrub(text: str) -> str:
    return _URL_RE.sub("<url>", text)

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
# Одна секунда float32 за одно чтение трубы и общий предел на чтение
# источника, чтобы зависшая сеть не держала воркер бесконечно.
STREAM_BLOCK_BYTES = SAMPLE_RATE * 4
MAX_STREAM_SECONDS = 7_200

_lock = threading.Lock()
_models: dict[str, object] = {}


class Recognizer:
    """Две ONNX-модели: русская с пунктуацией и английская.

    Модель грузится при первом обращении, поэтому конструктор дешёвый и
    его можно вызывать на каждый запрос.
    """

    def __init__(
        self,
        model_ru: str,
        model_en: str,
        quantization: str | None = "int8",
        threads: int = 0,
    ) -> None:
        self.model_ru = model_ru
        self.model_en = model_en
        self.quantization = quantization or None
        self.threads = max(0, int(threads or 0))

    # --- модели -----------------------------------------------------------

    def _model_for(self, language: str) -> tuple[str, bool]:
        """Имя модели для языка и нужен ли ей аргумент `language`.

        GigaAM понимает только русский и аргумент языка не принимает.
        Whisper многоязычная, ей язык передаём.
        """
        if (language or "ru").lower().startswith("en"):
            return self.model_en, True
        return self.model_ru, False

    def _load(self, model_id: str):
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

            logger.info("Загрузка ONNX-модели '%s' (quantization=%s)", model_id, self.quantization)
            options = None
            if self.threads:
                # 0 значит «пусть onnxruntime сам решит по числу ядер».
                import onnxruntime as ort

                options = ort.SessionOptions()
                options.intra_op_num_threads = self.threads
                options.inter_op_num_threads = 1
            model = onnx_asr.load_model(
                model_id,
                quantization=self.quantization,
                providers=["CPUExecutionProvider"],
                sess_options=options,
            )
            _models[model_id] = model
            logger.info("Модель '%s' загружена", model_id)
            return model

    def warm_up(self, language: str = "ru") -> bool:
        """Загрузить модель заранее, чтобы первый запрос не ждал диск.

        Пустой звук дешевле всего даёт рабочую ONNX-сессию и заодно
        проверяет, что модель действительно выполняет вычисление.
        Возвращает False, если прогрев не удался: тогда воркер не должен
        объявлять себя готовым.
        """
        model_id, needs_language = self._model_for(language)
        try:
            model = self._load(model_id)
            probe = np.zeros(SAMPLE_RATE // 2, dtype=np.float32)
            model.recognize(probe, **({"language": "ru"} if needs_language else {}))
            logger.info("Модель '%s' прогрев прошла", model_id)
            return True
        except Exception as exc:  # прогрев не должен ронять контейнер
            logger.error("Прогрев модели '%s' не удался: %s", model_id, exc)
            return False

    # --- аудио ------------------------------------------------------------

    @staticmethod
    def _resample(buf: np.ndarray, source_rate: int, target_rate: int = SAMPLE_RATE) -> np.ndarray:
        """Линейная передискретизация: качества хватает, зависимостей нет."""
        if source_rate == target_rate or buf.size == 0:
            return buf
        duration = buf.size / float(source_rate)
        target_size = int(round(duration * target_rate))
        if target_size <= 0:
            return np.zeros(0, dtype=np.float32)
        x_old = np.linspace(0.0, duration, num=buf.size, endpoint=False)
        x_new = np.linspace(0.0, duration, num=target_size, endpoint=False)
        return np.interp(x_new, x_old, buf).astype(np.float32)

    def _decode_with_soundfile(self, path: str) -> np.ndarray | None:
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
        return self._resample(buf, int(rate))

    def _decode_with_ffmpeg(self, path: str) -> np.ndarray | None:
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
            # str(TimeoutExpired) содержит всю команду, включая ссылку с токеном.
            logger.warning("ffmpeg не запустился: %s", _scrub(str(exc)))
            return None
        if completed.returncode != 0:
            stderr = _scrub(completed.stderr.decode("utf-8", "replace")).strip()
            logger.warning("ffmpeg вернул код %s: %s", completed.returncode, stderr[:400])
            return None
        return np.frombuffer(completed.stdout, dtype=np.float32).copy()

    def decode(self, path: str) -> np.ndarray | None:
        """Декодировать файл в моно float32 16 кГц."""
        buf = self._decode_with_soundfile(path)
        if buf is None:
            buf = self._decode_with_ffmpeg(path)
        if buf is None:
            logger.error("Не удалось декодировать аудио: %s", path)
            return None
        if buf.size == 0:
            logger.warning("Файл не содержит звука: %s", path)
        return buf

    def transcribe_source(
        self,
        source: str,
        language: str = "ru",
        max_seconds: int = 0,
        progress=None,
        total_seconds: int = 0,
    ) -> tuple[str | None, str | None, int | None]:
        """Распознать локальный файл или ссылку Telegram потоком.

        Ссылку ffmpeg читает сам, поэтому копии файла на диске нет. Звук
        приходит кусками по секунде: как только накопилось 25 секунд, кусок
        уходит в модель, а следующая секунда уже качается. Память не растёт
        с длиной записи.

        Третий элемент ответа — длительность, если запись оказалась длиннее
        `max_seconds`. У документов Telegram нет поля `duration`, поэтому
        лимит проверяется по декодированному звуку.
        """
        return self._transcribe_stream(
            source,
            language=language,
            max_seconds=max_seconds,
            progress=progress,
            total_seconds=total_seconds,
        )

    def _transcribe_stream(
        self,
        source: str,
        language: str = "ru",
        max_seconds: int = 0,
        progress=None,
        total_seconds: int = 0,
    ) -> tuple[str | None, str | None, int | None]:
        executable = shutil.which("ffmpeg")
        if executable is None:
            logger.error("ffmpeg не найден")
            return None, None, None

        command = [
            executable,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            source,
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

        model_id, needs_language = self._model_for(language)
        language_code = (language or "ru").lower()
        if language_code not in ("ru", "en"):
            language_code = "ru"
        try:
            model = self._load(model_id)
        except Exception:
            logger.exception("Не удалось загрузить модель %s", model_id)
            return None, None, None
        kwargs = {"language": language_code} if needs_language else {}

        errors = tempfile.TemporaryFile()
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=errors,
        )

        parts: list[str] = []
        buffer = np.zeros(0, dtype=np.float32)
        pending = b""
        processed = 0
        too_long: int | None = None
        started = time.monotonic()

        try:
            assert process.stdout is not None
            while True:
                block = process.stdout.read(STREAM_BLOCK_BYTES)
                if not block:
                    break
                if time.monotonic() - started > MAX_STREAM_SECONDS:
                    logger.error("Чтение источника идёт дольше %s с", MAX_STREAM_SECONDS)
                    break

                # Труба отдаёт произвольное число байт: хвост, не кратный
                # четырём, придерживаем до следующего чтения.
                data = pending + block
                usable = len(data) - len(data) % 4
                pending = data[usable:]
                if usable:
                    buffer = np.concatenate(
                        (buffer, np.frombuffer(data[:usable], dtype=np.float32))
                    )

                # Держим в памяти не больше 27 секунд: 25 на кусок плюс окно
                # поиска тихого места для разреза.
                while len(buffer) >= CHUNK_SAMPLES + CUT_SEARCH_SAMPLES:
                    cut = self._cut_point(buffer, 0, CHUNK_SAMPLES)
                    piece = buffer[:cut]
                    buffer = buffer[cut:].copy()
                    text = self._transcribe_chunk(model, piece, kwargs)
                    if text:
                        parts.append(text)
                    processed += len(piece)
                    if progress:
                        progress(processed, total_seconds)

                    if max_seconds and processed > max_seconds * SAMPLE_RATE:
                        too_long = int(round(processed / SAMPLE_RATE))
                        break

                if too_long:
                    break

            if too_long is None and len(buffer):
                if len(buffer) < MIN_MODEL_SAMPLES:
                    buffer = np.pad(buffer, (0, MIN_MODEL_SAMPLES - len(buffer)))
                text = self._transcribe_chunk(model, buffer, kwargs)
                if text:
                    parts.append(text)
                processed += len(buffer)
                if progress:
                    progress(processed, total_seconds)

        except Exception:
            logger.exception("Ошибка потокового распознавания (%s)", model_id)
            parts = []
        finally:
            if too_long:
                process.kill()
            try:
                process.stdout.close()  # type: ignore[union-attr]
            except Exception:
                pass
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            if process.returncode not in (0, None) and not parts:
                errors.seek(0)
                stderr = _scrub(errors.read().decode("utf-8", "replace")).strip()
                logger.warning(
                    "ffmpeg вернул код %s: %s", process.returncode, stderr[:400]
                )
            errors.close()

        if too_long:
            logger.info("Запись длиннее лимита: %s с > %s с", too_long, max_seconds)
            return None, None, too_long

        text = " ".join(part for part in parts if part) or None
        logger.info("Распознано %s символов (%s)", len(text or ""), model_id)
        return text, language_code, None

    # --- распознавание ----------------------------------------------------

    @staticmethod
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

    @staticmethod
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
        # При равной энергии берём самый поздний кадр, так ровный звук
        # режется точно по границе.
        best = int(len(energy) - 1 - np.argmin(energy[::-1]))
        return low + (best + 1) * CUT_FRAME_SAMPLES

    def _transcribe_chunk(self, model, chunk: np.ndarray, kwargs: dict) -> str | None:
        try:
            return self._extract_text(model.recognize(chunk, **kwargs))
        except Exception:
            if len(chunk) <= MIN_RETRY_SAMPLES:
                raise
            logger.warning(
                "Модель отклонила кусок %.1f с, делю пополам", len(chunk) / SAMPLE_RATE
            )
            middle = len(chunk) // 2
            parts = [
                text
                for text in (
                    self._transcribe_chunk(model, chunk[:middle], kwargs),
                    self._transcribe_chunk(model, chunk[middle:], kwargs),
                )
                if text
            ]
            return " ".join(parts) or None

    def _transcribe_chunked(self, model, buf: np.ndarray, kwargs: dict) -> str | None:
        """Прогнать запись кусками до 25 с и склеить результат пробелом."""
        if len(buf) < MIN_MODEL_SAMPLES:
            buf = np.pad(buf, (0, MIN_MODEL_SAMPLES - len(buf)))
        if len(buf) <= CHUNK_SAMPLES:
            return self._transcribe_chunk(model, buf, kwargs)

        parts: list[str] = []
        start = 0
        while start < len(buf):
            end = self._cut_point(buf, start, CHUNK_SAMPLES)
            text = self._transcribe_chunk(model, buf[start:end], kwargs)
            if text:
                parts.append(text)
            start = end
        return " ".join(parts) or None

    def transcribe_audio(
        self, audio: np.ndarray, language: str = "ru"
    ) -> tuple[str | None, str | None]:
        """Распознать готовый буфер 16 кГц."""
        model_id, needs_language = self._model_for(language)
        language_code = (language or "ru").lower()
        if language_code not in ("ru", "en"):
            language_code = "ru"
        try:
            model = self._load(model_id)
            kwargs = {"language": language_code} if needs_language else {}
            text = self._transcribe_chunked(model, np.asarray(audio, dtype=np.float32), kwargs)
            logger.info("Распознано %s символов (%s)", len(text or ""), model_id)
            return text, language_code
        except Exception:
            logger.exception("Ошибка распознавания (%s)", model_id)
            return None, None

    def transcribe_file(
        self, path: str, language: str = "ru"
    ) -> tuple[str | None, str | None]:
        """Декодировать файл и распознать его.

        Голосовое и видео-кружок идут одним путём: ffmpeg сам вытаскивает
        дорожку из контейнера, промежуточный mp3 не нужен.
        """
        audio = self.decode(path)
        if audio is None:
            return None, None
        return self.transcribe_audio(audio, language=language)
