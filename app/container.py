"""Сборка сервисов: единственное место, где инфраструктура встречается с правилами."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.infra.media import MediaStorage
from app.services.access import AccessService
from app.services.media import MediaService
from app.services.stats import StatsService
from app.services.transcription import TranscriptionService


@dataclass(frozen=True)
class Services:
    access: AccessService
    stats: StatsService
    transcription: TranscriptionService
    media: MediaService


def build_services(settings: Settings) -> Services:
    return Services(
        access=AccessService(settings.db_path, settings.admin_ids),
        stats=StatsService(settings.db_path),
        transcription=TranscriptionService(),
        media=MediaService(MediaStorage(settings.data_dir)),
    )
