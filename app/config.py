"""Настройки бота из переменных окружения.

Один модуль читает `.env` и отдаёт неизменяемый объект, чтобы остальные
слои не дёргали `os.getenv` и не расходились в значениях.
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


def _bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


@dataclass(frozen=True)
class Settings:
    """Всё, что бот и воркер берут из окружения."""

    token: str | None
    admin_ids: tuple[int, ...] = ()
    data_dir: str = "data"
    database_url: str = "postgresql://lazy:lazy@postgres:5432/lazy"

    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 0

    asr_model: str = "gigaam-v3-e2e-ctc"
    asr_model_en: str = "whisper-base"
    asr_quantization: str = "int8"
    asr_threads: int = 0
    warm_up_en: bool = True
    max_media_seconds: int = 300
    result_ttl_seconds: int = 3600

    # Разобранный `.env` держим рядом, чтобы не перечитывать файл в тестах.
    raw: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Settings":
        """Собрать настройки из окружения с безопасными значениями."""
        data_dir = os.getenv("DATA_DIR", "data").strip() or "data"
        database_url = (
            os.getenv("DATABASE_URL", "").strip()
            or "postgresql://lazy:lazy@postgres:5432/lazy"
        )

        return cls(
            token=(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip() or None,
            admin_ids=_int_list(os.getenv("ADMIN_ID")),
            data_dir=data_dir,
            database_url=database_url,
            redis_host=os.getenv("REDIS_HOST", "redis").strip() or "redis",
            redis_port=_int(os.getenv("REDIS_PORT"), 6379),
            redis_db=_int(os.getenv("REDIS_DB"), 0),
            asr_model=os.getenv("ASR_MODEL", "gigaam-v3-e2e-ctc").strip()
            or "gigaam-v3-e2e-ctc",
            asr_model_en=os.getenv("ASR_MODEL_EN", "whisper-base").strip() or "whisper-base",
            asr_quantization=(os.getenv("ASR_QUANTIZATION", "int8").strip() or "int8"),
            asr_threads=max(0, _int(os.getenv("ASR_THREADS"), 0)),
            warm_up_en=_bool(os.getenv("WARM_UP_EN"), True),
            max_media_seconds=max(1, _int(os.getenv("MAX_MEDIA_SECONDS"), 300)),
            result_ttl_seconds=max(60, _int(os.getenv("RESULT_TTL_SECONDS"), 3600)),
        )
