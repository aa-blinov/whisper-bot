"""Счётчики для администратора и запись истории запросов."""

from __future__ import annotations

from app.domain import Stats
from app.infra import database


class StatsService:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def overview(self) -> Stats:
        return database.stats(self.database_url)

    def record(
        self,
        user_id: int,
        duration_seconds: float,
        file_type: str,
        text: str,
        language: str | None = None,
    ) -> None:
        database.record_task(
            self.database_url, user_id, duration_seconds, file_type, text, language
        )
