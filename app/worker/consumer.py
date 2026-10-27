"""Точка входа воркера: логирование, прогрев моделей, Huey consumer."""

from __future__ import annotations

import logging
import os
import sys
import time

from huey.bin.huey_consumer import consumer_main

from app.config import Settings
from app.infra.asr import Recognizer

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

READY_FILE = "/tmp/worker-ready"


def main() -> None:
    settings = Settings.from_env()
    os.makedirs(settings.data_dir, exist_ok=True)

    recognizer = Recognizer(
        settings.asr_model, settings.asr_model_en, settings.asr_quantization
    )

    started = time.time()
    # Русскую модель грузим всегда: это основной путь.
    recognizer.warm_up()
    # Английскую тоже, если она включена: иначе первый английский запрос
    # висит на скачивании 107 МБ и выглядит как зависший бот.
    if settings.warm_up_en and settings.asr_model_en != settings.asr_model:
        recognizer.warm_up("en")
    logger.info("Прогрев моделей занял %.1f с", time.time() - started)

    # Файл готовности читает healthcheck в docker-compose: бот увидит
    # healthy воркер только после того, как модель действительно посчитала.
    with open(READY_FILE, "w", encoding="utf-8") as handle:
        handle.write("ready\n")

    sys.argv = ["huey_consumer.py", "app.infra.queue.huey"]
    consumer_main()


if __name__ == "__main__":
    main()
