"""Постановка распознавания в очередь и ожидание результата."""

from __future__ import annotations

import asyncio
import logging

from huey.contrib.asyncio import aget_result

from app.domain import Transcript
from app.infra.queue import huey, transcribe_task

logger = logging.getLogger(__name__)


class TranscriptionTimeout(RuntimeError):
    """Воркер не ответил за отведённое время."""


class TranscriptionService:
    """Один запрос распознавания: задача в Huey, потом ожидание ответа."""

    def __init__(
        self,
        timeout_min: int = 120,
        timeout_max: int = 900,
        task=transcribe_task,
    ) -> None:
        self.timeout_min = timeout_min
        self.timeout_max = timeout_max
        self._task = task

    def timeout_for(self, duration: int) -> int:
        """Сколько ждать: длиннее запись, дольше распознавание, но не бесконечно."""
        return min(self.timeout_max, max(self.timeout_min, int(duration or 0) * 2))

    async def transcribe(
        self,
        source: str,
        file_type: str,
        language: str,
        duration: int = 0,
    ) -> Transcript | None:
        """Распознать источник: ссылку Telegram или локальный путь."""
        task = self._task(source, file_type, language)
        try:
            result = await asyncio.wait_for(
                aget_result(task, backoff=1.2, max_delay=1.0, preserve=False),
                timeout=self.timeout_for(duration),
            )
        except asyncio.TimeoutError as exc:
            logger.error("Воркер не ответил за отведённое время (%s с)", duration)
            raise TranscriptionTimeout("воркер не ответил вовремя") from exc

        # RedisExpireHuey не удаляет результат при чтении, только ждёт TTL.
        # Чистим сразу: иначе каждый запрос оставляет ключ на час.
        self._discard(task.id)

        if not isinstance(result, (list, tuple)) or not result or not result[0]:
            return None

        text = str(result[0])
        recognized_language = result[1] if len(result) > 1 and result[1] else language
        return Transcript(text=text, language=recognized_language)

    @staticmethod
    def _discard(task_id: str) -> None:
        try:
            huey.storage.delete_data(task_id)
        except Exception as exc:
            logger.debug("Не удалось удалить результат задачи %s: %s", task_id, exc)
