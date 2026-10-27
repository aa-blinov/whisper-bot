"""Файлы медиа как часть приложения: где скачанное лежит и когда удаляется.

Тонкая обёртка над `app.infra.media`: обработчики работают с сервисом, а
не с инфраструктурой напрямую.
"""

from __future__ import annotations

from app.infra.media import MediaStorage


class MediaService:
    def __init__(self, storage: MediaStorage) -> None:
        self.storage = storage

    def prepare(self) -> None:
        self.storage.ensure()

    def new_path(self, file_type: str) -> str:
        return self.storage.new_path(file_type)

    def remove(self, path: str | None) -> None:
        self.storage.remove(path)
