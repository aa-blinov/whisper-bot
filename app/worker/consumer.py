"""Точка входа воркера: логирование, прогрев модели, Huey consumer."""

from __future__ import annotations

import logging
import os
import sys

from huey.bin.huey_consumer import consumer_main

from app.config import Settings
from app.infra.asr import Recognizer

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


def main() -> None:
    settings = Settings.from_env()
    os.makedirs(settings.data_dir, exist_ok=True)
    Recognizer(
        settings.asr_model, settings.asr_model_en, settings.asr_quantization
    ).warm_up()
    sys.argv = ["huey_consumer.py", "app.infra.queue.huey"]
    consumer_main()


if __name__ == "__main__":
    main()
