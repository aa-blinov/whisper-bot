"""Доступ к сервисам из обработчиков.

Сервисы собираются один раз в `build_application` и лежат в `bot_data`,
поэтому обработчики не создают соединений и не читают окружение.
"""

from __future__ import annotations

from telegram.ext import ContextTypes

from app.config import Settings
from app.services.access import AccessService
from app.services.stats import StatsService
from app.services.transcription import TranscriptionService


def settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.bot_data["settings"]


def access(context: ContextTypes.DEFAULT_TYPE) -> AccessService:
    return context.bot_data["access"]


def stats(context: ContextTypes.DEFAULT_TYPE) -> StatsService:
    return context.bot_data["stats"]


def transcription(context: ContextTypes.DEFAULT_TYPE) -> TranscriptionService:
    return context.bot_data["transcription"]
