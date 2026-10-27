"""Файлы на диске: скачанное медиа и уборка после распознавания."""

from __future__ import annotations

import logging
import os
import uuid

logger = logging.getLogger(__name__)


class MediaStorage:
    """Куда складывать скачанное и откуда его потом убирать."""

    def __init__(self, data_dir: str) -> None:
        self.data_dir = data_dir

    def ensure(self) -> None:
        os.makedirs(self.data_dir, exist_ok=True)

    def new_path(self, file_type: str) -> str:
        """Уникальный путь под скачивание; расширение `.bin` для любого медиа."""
        self.ensure()
        return os.path.join(self.data_dir, f"{uuid.uuid4().hex}_{file_type}.bin")

    @staticmethod
    def remove(path: str | None) -> None:
        """Удалить файл, если он ещё есть. Ошибку только логируем."""
        if not path:
            return
        try:
            if os.path.exists(path):
                os.remove(path)
                logger.info("Файл удалён: %s", path)
        except OSError as exc:
            logger.warning("Не удалось удалить файл %s: %s", path, exc)
