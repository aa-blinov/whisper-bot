"""Постановка распознавания в очередь и ожидание результата."""

from __future__ import annotations

import asyncio
import logging

from huey.contrib.asyncio import aget_result

from app.domain import Transcript
from app.infra.queue import transcribe_task

logger = logging.getLogger(__name__)


class TranscriptionTimeout(RuntimeError):
    """Воркер не ответил за отведённое время."""


class TranscriptionService:
    """Один запрос распознавания: задача в Huey, потом ожидание ответа."""

    def __init__(
        self,
        timeout_min: int = 60,
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
        file_path: str,
        file_type: str,
        language: str,
        duration: int = 0,
    ) -> Transcript | None:
        """Распознать файл. None, если модель не расслышала текст."""
        task = self._task(file_path, file_type, language)
        try:
            result = await asyncio.wait_for(
                aget_result(task, backoff=1.2, max_delay=1.0, preserve=False),
                timeout=self.timeout_for(duration),
            )
        except asyncio.TimeoutError as exc:
            logger.error("Воркер не ответил за отведённое время (%s с)", duration)
            raise TranscriptionTimeout("воркер не ответил вовремя") from exc

        if not isinstance(result, (list, tuple)) or not result or not result[0]:
            return None

        text = str(result[0])
        recognized_language = result[1] if len(result) > 1 and result[1] else language
        return Transcript(text=text, language=recognized_language)
