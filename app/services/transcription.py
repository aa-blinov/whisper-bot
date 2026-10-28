"""Постановка распознавания в очередь и ожидание результата."""

from __future__ import annotations

import asyncio
import logging
import time

import redis.asyncio as aioredis
from huey.contrib.asyncio import aget_result

from app.domain import Transcript
from app.infra.queue import huey, transcribe_task

logger = logging.getLogger(__name__)

# Как часто спрашивать у Redis, сколько уже обработано, пока идёт задача.
PROGRESS_POLL_SECONDS = 5.0


class TranscriptionTimeout(RuntimeError):
    """Воркер не ответил за отведённое время."""


class TranscriptTooLong(RuntimeError):
    """Запись оказалась длиннее лимита, который знает воркер."""

    def __init__(self, seconds: int) -> None:
        super().__init__(f"запись длится {seconds} с")
        self.seconds = seconds


class TranscriptionService:
    """Один запрос распознавания: задача в Huey, потом ожидание ответа."""

    def __init__(
        self,
        timeout_min: int = 120,
        timeout_max: int = 3600,
        task=transcribe_task,
        redis_host: str = "redis",
        redis_port: int = 6379,
        redis_db: int = 0,
    ) -> None:
        self.timeout_min = timeout_min
        self.timeout_max = timeout_max
        self._task = task
        self._redis = aioredis.Redis(
            host=redis_host,
            port=redis_port,
            db=redis_db,
            socket_connect_timeout=2,
            socket_timeout=2,
        )

    def timeout_for(self, duration: int) -> int:
        """Сколько ждать: длиннее запись, дольше распознавание, но не бесконечно."""
        return min(self.timeout_max, max(self.timeout_min, int(duration or 0) * 2))

    async def transcribe(
        self,
        source: str,
        file_type: str,
        language: str,
        duration: int = 0,
        progress_key: str = "",
        on_progress=None,
    ) -> Transcript | None:
        """Распознать источник: ссылку Telegram или локальный путь.

        `progress_key` воркер заполняет числом обработанных сэмплов, а
        `on_progress` получает их, пока идёт ожидание.
        """
        task = self._task(source, file_type, language, progress_key, duration)
        started = time.monotonic()
        limit = self.timeout_for(duration)
        pending = asyncio.ensure_future(
            aget_result(task, backoff=1.2, max_delay=1.0, preserve=False)
        )
        result = None
        try:
            while True:
                left = limit - (time.monotonic() - started)
                if left <= 0:
                    pending.cancel()
                    raise asyncio.TimeoutError
                done, _ = await asyncio.wait(
                    {pending}, timeout=min(PROGRESS_POLL_SECONDS, left)
                )
                if done:
                    result = pending.result()
                    break
                if on_progress:
                    try:
                        await self._report(progress_key, on_progress)
                    except Exception as exc:
                        logger.debug("Не удалось прочитать прогресс: %s", exc)
        except asyncio.TimeoutError as exc:
            logger.error("Воркер не ответил за отведённое время (%s с)", duration)
            raise TranscriptionTimeout("воркер не ответил вовремя") from exc
        finally:
            await self._cleanup(progress_key)

        # RedisExpireHuey не удаляет результат при чтении, только ждёт TTL.
        # Чистим сразу: иначе каждый запрос оставляет ключ на час.
        self._discard(task.id)

        if not isinstance(result, (list, tuple)) or not result:
            return None

        # Воркер отвечает (текст, язык, длительность-если-слишком-длинно).
        too_long = result[2] if len(result) > 2 else None
        if too_long:
            raise TranscriptTooLong(int(too_long))

        if not result[0]:
            return None

        text = str(result[0])
        recognized_language = result[1] if len(result) > 1 and result[1] else language
        return Transcript(text=text, language=recognized_language)

    async def _report(self, progress_key: str, on_progress) -> None:
        if not progress_key:
            return
        raw = await self._redis.get(progress_key)
        if not raw:
            return
        processed, _, total = raw.decode("utf-8", "replace").partition(":")
        try:
            got = on_progress(int(processed), int(total or 0))
        except ValueError:
            return
        if asyncio.iscoroutine(got):
            await got

    async def _cleanup(self, progress_key: str) -> None:
        if not progress_key:
            return
        try:
            await self._redis.delete(progress_key)
        except Exception as exc:
            logger.debug("Не удалось убрать ключ прогресса: %s", exc)

    @staticmethod
    def _discard(task_id: str) -> None:
        try:
            huey.storage.delete_data(task_id)
        except Exception as exc:
            logger.debug("Не удалось удалить результат задачи %s: %s", task_id, exc)
