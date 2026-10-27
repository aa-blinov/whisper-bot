"""Точка входа бота: настройки, база, long polling."""

from __future__ import annotations

import logging
import os

from telegram import Update

from app.bot.app import build_application
from app.config import Settings
from app.container import build_services
from app.infra import database

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def main() -> int:
    settings = Settings.from_env()
    if not settings.token:
        logger.error("TELEGRAM_BOT_TOKEN не задан, бот не может стартовать.")
        return 1

    os.makedirs(settings.data_dir, exist_ok=True)
    database.init_db(settings.database_url, settings.admin_ids)
    if not settings.admin_ids and not database.has_admins(settings.database_url):
        logger.warning(
            "ADMIN_ID не задан: администратором станет первый, кто напишет /start. "
            "Укажи ADMIN_ID в .env, чтобы закрепить админа."
        )

    application = build_application(settings, build_services(settings))
    logger.info("Запуск long polling")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        # Ничего не выбрасываем: сообщения, пришедшие пока бот лежал,
        # обработаются после старта.
        drop_pending_updates=False,
        close_loop=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
