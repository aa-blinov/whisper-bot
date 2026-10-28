"""Сборка сервисов: единственное место, где инфраструктура встречается с правилами."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.services.access import AccessService
from app.services.stats import StatsService
from app.services.transcription import TranscriptionService


@dataclass(frozen=True)
class Services:
    access: AccessService
    stats: StatsService
    transcription: TranscriptionService


def build_services(settings: Settings) -> Services:
    return Services(
        access=AccessService(settings.database_url, settings.admin_ids),
        stats=StatsService(settings.database_url),
        transcription=TranscriptionService(
            redis_host=settings.redis_host,
            redis_port=settings.redis_port,
            redis_db=settings.redis_db,
        ),
    )
