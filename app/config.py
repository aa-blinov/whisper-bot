"""Настройки бота из переменных окружения.

Один модуль читает `.env` один раз и отдаёт неизменяемый объект, чтобы
остальные файлы не дёргали `os.getenv` и не расходились в значениях.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _int_list(raw: str | None) -> tuple[int, ...]:
    """Разобрать список Telegram ID через запятую, пробел или точку с запятой.

    Нечисловые куски пропускаются: из-за одной опечатки бот не должен
    падать на старте, как это было с `ADMIN_ID`.
    """
    if not raw:
        return ()
    cleaned = raw.replace(";", ",").replace(" ", ",")
    ids: list[int] = []
    for part in cleaned.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            continue
    return tuple(ids)


def _int(raw: str | None, default: int) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    """Всё, что бот и воркер берут из окружения."""

    token: str | None
    admin_ids: tuple[int, ...] = ()
    data_dir: str = "data"
    db_path: str = "data/bot_database.db"

    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 0

    asr_model: str = "gigaam-v3-e2e-ctc"
    asr_model_en: str = "whisper-base"
    asr_quantization: str = "int8"
    asr_threads: int = 4
    max_media_seconds: int = 300

    openrouter_api_key: str | None = None
    openrouter_model: str = "openai/gpt-oss-20b:free"

    # Разобранный `.env` держим рядом, чтобы не перечитывать файл в тестах.
    raw: dict[str, str] = field(default_factory=dict)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openrouter_api_key)


def load() -> Settings:
    """Собрать настройки из окружения (с подстановкой безопасных значений)."""
    data_dir = os.getenv("DATA_DIR", "data").strip() or "data"
    db_path = os.getenv("DB_PATH", "").strip() or os.path.join(data_dir, "bot_database.db")

    return Settings(
        token=(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip() or None,
        admin_ids=_int_list(os.getenv("ADMIN_ID")),
        data_dir=data_dir,
        db_path=db_path,
        redis_host=os.getenv("REDIS_HOST", "redis").strip() or "redis",
        redis_port=_int(os.getenv("REDIS_PORT"), 6379),
        redis_db=_int(os.getenv("REDIS_DB"), 0),
        asr_model=os.getenv("ASR_MODEL", "gigaam-v3-e2e-ctc").strip() or "gigaam-v3-e2e-ctc",
        asr_model_en=os.getenv("ASR_MODEL_EN", "whisper-base").strip() or "whisper-base",
        asr_quantization=(os.getenv("ASR_QUANTIZATION", "int8").strip() or "int8"),
        asr_threads=max(1, _int(os.getenv("ASR_THREADS"), 4)),
        max_media_seconds=max(1, _int(os.getenv("MAX_MEDIA_SECONDS"), 300)),
        openrouter_api_key=(os.getenv("OPENROUTER_API_KEY") or "").strip() or None,
        openrouter_model=os.getenv("OPENROUTER_MODEL_NAME", "openai/gpt-oss-20b:free").strip()
        or "openai/gpt-oss-20b:free",
    )


settings = load()
