"""Точка входа воркера: прогреть модель и запустить Huey consumer."""

import logging
import os
import sys

from huey.bin.huey_consumer import consumer_main

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

if __name__ == "__main__":
    from huey_tasks import warm_up

    warm_up()
    sys.argv = ["huey_consumer.py", "huey_tasks.huey"]
    consumer_main()
