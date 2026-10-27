"""Postgres: пользователи и история запросов.

Почему не SQLite: историю пишет бот, а читает статистику он же, но при
нескольких процессах один файл становится точкой сериализации. Postgres
даёт нормальную параллельную запись и переживает перезапуск контейнера.

Схема создаётся и дополняется при старте. Соединения берутся из пула:
запросы идут из цикла событий бота и из потоков, пул сам ждёт свободное
соединение.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.domain import Stats, User

logger = logging.getLogger(__name__)

USERS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        is_admin BOOLEAN NOT NULL DEFAULT FALSE,
        first_name TEXT NOT NULL DEFAULT '',
        last_name TEXT NOT NULL DEFAULT '',
        username TEXT NOT NULL DEFAULT '',
        language TEXT NOT NULL DEFAULT 'ru',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
"""

TASKS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS tasks (
        task_id BIGSERIAL PRIMARY KEY,
        user_id BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
        timestamp TIMESTAMPTZ NOT NULL,
        duration_seconds DOUBLE PRECISION,
        original_file_type TEXT,
        recognized_text TEXT,
        language TEXT
    )
"""

INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_tasks_timestamp ON tasks(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id)",
)

_pools: dict[str, ConnectionPool] = {}
_pools_lock = threading.Lock()


def pool(database_url: str) -> ConnectionPool:
    """Пул соединений, один на строку подключения."""
    with _pools_lock:
        existing = _pools.get(database_url)
        if existing is not None:
            return existing
        created = ConnectionPool(
            database_url,
            min_size=1,
            max_size=8,
            open=False,
            kwargs={"row_factory": dict_row},
        )
        created.open(wait=True, timeout=15)
        _pools[database_url] = created
        return created


@contextmanager
def connect(database_url: str):
    """Соединение из пула: коммит при выходе, возврат в пул всегда."""
    with pool(database_url).connection() as conn:
        yield conn


def close_all() -> None:
    """Закрыть пулы: нужно тестам и аккуратному завершению."""
    with _pools_lock:
        for container in _pools.values():
            container.close()
        _pools.clear()


def init_db(database_url: str, admin_ids: tuple[int, ...] = ()) -> None:
    """Создать схему и завести администраторов из окружения."""
    try:
        with connect(database_url) as conn:
            conn.execute(USERS_SCHEMA)
            conn.execute(TASKS_SCHEMA)
            for statement in INDEXES:
                conn.execute(statement)
            for admin_id in admin_ids:
                conn.execute(
                    """INSERT INTO users (user_id, is_admin) VALUES (%s, TRUE)
                       ON CONFLICT (user_id) DO UPDATE SET is_admin = TRUE""",
                    (admin_id,),
                )
        logger.info("Схема базы данных готова")
    except psycopg.Error as exc:
        logger.exception("Не удалось инициализировать базу данных: %s", exc)


def _row_to_user(row: dict) -> User:
    return User(
        user_id=int(row["user_id"]),
        is_admin=bool(row["is_admin"]),
        first_name=row["first_name"] or "",
        last_name=row["last_name"] or "",
        username=row["username"] or "",
        language=row["language"] or "ru",
        created_at=row["created_at"].isoformat() if row["created_at"] else None,
    )


def get_user(database_url: str, user_id: int) -> User | None:
    try:
        with connect(database_url) as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE user_id = %s", (user_id,)
            ).fetchone()
        return _row_to_user(row) if row else None
    except psycopg.Error as exc:
        logger.error("Ошибка чтения пользователя %s: %s", user_id, exc)
        return None


def list_users(database_url: str) -> list[User]:
    """Все допущенные, администраторы первыми, затем по имени."""
    try:
        with connect(database_url) as conn:
            rows = conn.execute(
                """SELECT * FROM users
                   ORDER BY is_admin DESC, LOWER(first_name), user_id"""
            ).fetchall()
        return [_row_to_user(row) for row in rows]
    except psycopg.Error as exc:
        logger.error("Ошибка чтения списка пользователей: %s", exc)
        return []


def count_users(database_url: str) -> int:
    try:
        with connect(database_url) as conn:
            return int(conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"])
    except psycopg.Error as exc:
        logger.error("Ошибка подсчёта пользователей: %s", exc)
        return 0


def has_admins(database_url: str) -> bool:
    try:
        with connect(database_url) as conn:
            row = conn.execute(
                "SELECT 1 AS one FROM users WHERE is_admin LIMIT 1"
            ).fetchone()
        return row is not None
    except psycopg.Error as exc:
        logger.error("Ошибка проверки администраторов: %s", exc)
        return False


def add_user(
    database_url: str,
    user_id: int,
    *,
    is_admin: bool = False,
    first_name: str = "",
    last_name: str = "",
    username: str = "",
) -> bool:
    """Добавить или обновить пользователя. True, если запись новая."""
    try:
        with connect(database_url) as conn:
            row = conn.execute(
                """INSERT INTO users (user_id, is_admin, first_name, last_name, username)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (user_id) DO UPDATE SET
                       first_name = COALESCE(NULLIF(EXCLUDED.first_name, ''), users.first_name),
                       last_name = COALESCE(NULLIF(EXCLUDED.last_name, ''), users.last_name),
                       username = COALESCE(NULLIF(EXCLUDED.username, ''), users.username),
                       is_admin = users.is_admin OR EXCLUDED.is_admin
                   RETURNING (xmax = 0) AS inserted""",
                (user_id, is_admin, first_name or "", last_name or "", username or ""),
            ).fetchone()
        created = bool(row and row["inserted"])
        logger.info("Пользователь %s %s", "добавлен" if created else "обновлён", user_id)
        return created
    except psycopg.Error as exc:
        logger.error("Ошибка при добавлении пользователя %s: %s", user_id, exc)
        return False


def remove_user(database_url: str, user_id: int) -> bool:
    """Убрать пользователя из списка. True, если он там был.

    История остаётся: внешний ключ объявлен с ON DELETE SET NULL, поэтому
    запросы человека остаются в таблице без привязки к пользователю.
    """
    try:
        with connect(database_url) as conn:
            cursor = conn.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
            removed = cursor.rowcount > 0
        if removed:
            logger.info("Пользователь %s удалён", user_id)
        return removed
    except psycopg.Error as exc:
        logger.error("Ошибка при удалении пользователя %s: %s", user_id, exc)
        return False


def set_language(database_url: str, user_id: int, language: str) -> None:
    """Запомнить выбранный язык, чтобы он переживал перезапуск бота."""
    try:
        with connect(database_url) as conn:
            conn.execute(
                "UPDATE users SET language = %s WHERE user_id = %s",
                (language, user_id),
            )
    except psycopg.Error as exc:
        logger.error("Ошибка сохранения языка %s: %s", user_id, exc)


def record_task(
    database_url: str,
    user_id: int,
    duration_seconds: float,
    file_type: str,
    text: str,
    language: str | None = None,
) -> None:
    try:
        with connect(database_url) as conn:
            conn.execute(
                """INSERT INTO tasks
                   (user_id, timestamp, duration_seconds, original_file_type,
                    recognized_text, language)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (user_id, datetime.now(), duration_seconds, file_type, text, language),
            )
    except psycopg.Error as exc:
        logger.error("Ошибка записи запроса пользователя %s: %s", user_id, exc)


def stats(database_url: str) -> Stats:
    """Счётчики для `/stats`: пользователи, запросы за сегодня и за неделю."""
    try:
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=7)

        with connect(database_url) as conn:
            total_users = int(
                conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
            )
            today_active = int(
                conn.execute(
                    "SELECT COUNT(DISTINCT user_id) AS n FROM tasks WHERE timestamp >= %s",
                    (today_start,),
                ).fetchone()["n"]
            )
            today_requests = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM tasks WHERE timestamp >= %s",
                    (today_start,),
                ).fetchone()["n"]
            )
            today_new = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM users WHERE created_at >= %s",
                    (today_start,),
                ).fetchone()["n"]
            )
            week_active = int(
                conn.execute(
                    "SELECT COUNT(DISTINCT user_id) AS n FROM tasks WHERE timestamp >= %s",
                    (week_start,),
                ).fetchone()["n"]
            )
            week_requests = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM tasks WHERE timestamp >= %s",
                    (week_start,),
                ).fetchone()["n"]
            )
            week_new = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM users WHERE created_at >= %s",
                    (week_start,),
                ).fetchone()["n"]
            )

        return Stats(
            total_users=total_users,
            today_active=today_active,
            today_requests=today_requests,
            today_new=today_new,
            week_active=week_active,
            week_requests=week_requests,
            week_new=week_new,
        )
    except psycopg.Error as exc:
        logger.error("Ошибка чтения статистики: %s", exc)
        return Stats()
