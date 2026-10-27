"""Кто может пользоваться ботом и кто здесь администратор.

Сервис ничего не знает про Telegram: он отвечает на вопросы «пускать или
нет», «кто админ» и «выдать или закрыть доступ». Обработчики только
показывают результат.
"""

from __future__ import annotations

import logging

from app.domain import User
from app.infra import database

logger = logging.getLogger(__name__)


class AccessService:
    def __init__(self, database_url: str, admin_ids: tuple[int, ...] = ()) -> None:
        self.database_url = database_url
        self.admin_ids = tuple(admin_ids)

    # --- вопросы ----------------------------------------------------------

    def is_admin(self, user_id: int | None) -> bool:
        """Админом считается тот, кто указан в `ADMIN_ID` или помечен в базе."""
        if user_id is None:
            return False
        if user_id in self.admin_ids:
            return True
        user = database.get_user(self.database_url, user_id)
        return bool(user and user.is_admin)

    def is_allowed(self, user_id: int | None) -> bool:
        if user_id is None:
            return False
        return database.get_user(self.database_url, user_id) is not None

    def has_admin(self) -> bool:
        """Есть ли хоть один админ: в окружении или в базе."""
        return bool(self.admin_ids) or database.has_admins(self.database_url)

    def admins(self) -> list[int]:
        """Все админы: из окружения и из базы, без повторов."""
        found = list(dict.fromkeys(self.admin_ids))
        for user in database.list_users(self.database_url):
            if user.is_admin and user.user_id not in found:
                found.append(user.user_id)
        return found

    def count(self) -> int:
        return database.count_users(self.database_url)

    def all(self) -> list[User]:
        return database.list_users(self.database_url)

    def get(self, user_id: int) -> User | None:
        return database.get_user(self.database_url, user_id)

    # --- изменения --------------------------------------------------------

    def register(
        self, user_id: int, first_name: str = "", last_name: str = "", username: str = ""
    ) -> None:
        """Обновить имя и username, если человек их сменил в Telegram."""
        database.add_user(
            self.database_url,
            user_id,
            first_name=first_name,
            last_name=last_name,
            username=username,
        )

    def grant(
        self,
        user_id: int,
        first_name: str = "",
        last_name: str = "",
        username: str = "",
        is_admin: bool = False,
    ) -> bool:
        """Выдать доступ. True, если человек появился в списке впервые."""
        return database.add_user(
            self.database_url,
            user_id,
            is_admin=is_admin,
            first_name=first_name,
            last_name=last_name,
            username=username,
        )

    def revoke(self, user_id: int) -> bool:
        return database.remove_user(self.database_url, user_id)

    def claim_first_admin(self, user_id: int, **profile) -> bool:
        """Пока админа нет ни в `.env`, ни в базе, первый написавший становится им.

        True, если запись действительно удалась: если база не пишется,
        вызывающий не должен считать человека админом.
        """
        if self.admin_ids or database.has_admins(self.database_url):
            return False
        granted = self.grant(user_id, is_admin=True, **profile)
        if not granted:
            logger.error("Не удалось записать первого администратора %s", user_id)
            return False
        logger.warning("ADMIN_ID не задан: администратором стал первый написавший, %s", user_id)
        return True

    # --- язык -------------------------------------------------------------

    def language(self, user_id: int, default: str = "ru") -> str:
        user = database.get_user(self.database_url, user_id)
        return (user.language if user else None) or default

    def set_language(self, user_id: int, language: str) -> None:
        database.set_language(self.database_url, user_id, language)
