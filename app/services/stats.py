"""Счётчики для администратора и запись истории запросов."""

from __future__ import annotations

from app.domain import Stats
from app.infra import database


class StatsService:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def overview(self) -> Stats:
        return database.stats(self.db_path)

    def record(
        self,
        user_id: int,
        duration_seconds: float,
        file_type: str,
        text: str,
        language: str | None = None,
    ) -> None:
        database.record_task(
            self.db_path, user_id, duration_seconds, file_type, text, language
        )
