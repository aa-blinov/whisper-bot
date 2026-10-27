"""SQLite: список допущенных пользователей и история запросов.

Схема создаётся и дополняется при старте, поэтому база, оставшаяся от
старой версии, продолжает работать: недостающие колонки добавляются, а не
пересоздают таблицу.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

USERS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        is_admin INTEGER NOT NULL DEFAULT 0,
        first_name TEXT DEFAULT '',
        last_name TEXT DEFAULT '',
        username TEXT DEFAULT '',
        language TEXT NOT NULL DEFAULT 'ru',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
"""

TASKS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS tasks (
        task_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        timestamp TEXT NOT NULL,
        duration_seconds REAL,
        original_file_type TEXT,
        recognized_text TEXT,
        language TEXT,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
"""

USER_COLUMNS = (
    ("first_name", "TEXT DEFAULT ''"),
    ("last_name", "TEXT DEFAULT ''"),
    ("username", "TEXT DEFAULT ''"),
    ("language", "TEXT NOT NULL DEFAULT 'ru'"),
    ("created_at", "TEXT"),
)

TASK_COLUMNS = (("language", "TEXT"),)


def connect(db_path: str) -> sqlite3.Connection:
    """Соединение с доступом к колонкам по имени.

    Внешние ключи намеренно не включаем: удаление доступа не должно
    стирать историю запросов, на которой считает `/stats`. Ограничение
    объявлено в схеме, но SQLite его не проверяет.
    """
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _add_missing_columns(conn: sqlite3.Connection, table: str, columns) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, decl in columns:
        if name in existing:
            continue
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        except sqlite3.OperationalError as exc:  # колонка уже есть в другой версии
            logger.warning("Миграция %s.%s не удалась: %s", table, name, exc)


def init_db(db_path: str, admin_ids: tuple[int, ...] = ()) -> None:
    """Создать схему, дополнить её и завести администраторов из окружения."""
    try:
        with connect(db_path) as conn:
            conn.execute(USERS_SCHEMA)
            conn.execute(TASKS_SCHEMA)
            _add_missing_columns(conn, "users", USER_COLUMNS)
            _add_missing_columns(conn, "tasks", TASK_COLUMNS)
            # `created_at` появился позже: старым строкам ставим текущее время,
            # чтобы статистика не падала на пустом значении.
            conn.execute(
                "UPDATE users SET created_at = datetime('now') "
                "WHERE created_at IS NULL OR created_at = ''"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_timestamp ON tasks(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id)")

            for admin_id in admin_ids:
                row = conn.execute(
                    "SELECT user_id FROM users WHERE user_id = ?", (admin_id,)
                ).fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO users (user_id, is_admin) VALUES (?, 1)", (admin_id,)
                    )
                    logger.info("Администратор %s добавлен в базу при старте", admin_id)
                else:
                    conn.execute(
                        "UPDATE users SET is_admin = 1 WHERE user_id = ?", (admin_id,)
                    )
            conn.commit()
        logger.info("База данных '%s' готова", db_path)
    except sqlite3.Error as exc:
        logger.exception("Не удалось инициализировать базу данных: %s", exc)


def _profile_values(first_name: str, last_name: str, username: str) -> tuple[str, str, str]:
    return (first_name or "", last_name or "", username or "")


def add_user(
    db_path: str,
    user_id: int,
    *,
    is_admin: bool = False,
    first_name: str = "",
    last_name: str = "",
    username: str = "",
) -> bool:
    """Добавить или обновить пользователя. True, если запись новая."""
    try:
        with connect(db_path) as conn:
            row = conn.execute(
                "SELECT user_id FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            created = row is None
            first_name, last_name, username = _profile_values(
                first_name, last_name, username
            )
            if created:
                conn.execute(
                    """INSERT INTO users (user_id, is_admin, first_name, last_name, username)
                       VALUES (?, ?, ?, ?, ?)""",
                    (user_id, int(is_admin), first_name, last_name, username),
                )
            else:
                conn.execute(
                    """UPDATE users
                       SET first_name = COALESCE(NULLIF(?, ''), first_name),
                           last_name = COALESCE(NULLIF(?, ''), last_name),
                           username = COALESCE(NULLIF(?, ''), username),
                           is_admin = MAX(is_admin, ?)
                       WHERE user_id = ?""",
                    (first_name, last_name, username, int(is_admin), user_id),
                )
            conn.commit()
        logger.info("Пользователь %s %s", "добавлен" if created else "обновлён", user_id)
        return created
    except sqlite3.Error as exc:
        logger.error("Ошибка при добавлении пользователя %s: %s", user_id, exc)
        return False


def remove_user(db_path: str, user_id: int) -> bool:
    """Удалить пользователя из списка допущенных. True, если он там был."""
    try:
        with connect(db_path) as conn:
            cursor = conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            conn.commit()
            removed = cursor.rowcount > 0
        if removed:
            logger.info("Пользователь %s удалён", user_id)
        return removed
    except sqlite3.Error as exc:
        logger.error("Ошибка при удалении пользователя %s: %s", user_id, exc)
        return False


def is_user_allowed(db_path: str, user_id: int) -> bool:
    try:
        with connect(db_path) as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM users WHERE user_id = ?", (user_id,)
                ).fetchone()
                is not None
            )
    except sqlite3.Error as exc:
        logger.error("Ошибка проверки доступа %s: %s", user_id, exc)
        return False


def get_user(db_path: str, user_id: int) -> dict | None:
    try:
        with connect(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        return dict(row) if row else None
    except sqlite3.Error as exc:
        logger.error("Ошибка чтения пользователя %s: %s", user_id, exc)
        return None


def get_all_users(db_path: str) -> list[dict]:
    """Все допущенные, администраторы первыми, затем по имени."""
    try:
        with connect(db_path) as conn:
            rows = conn.execute(
                """SELECT * FROM users
                   ORDER BY is_admin DESC, LOWER(COALESCE(first_name, '')), user_id"""
            ).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error as exc:
        logger.error("Ошибка чтения списка пользователей: %s", exc)
        return []


def count_users(db_path: str) -> int:
    try:
        with connect(db_path) as conn:
            return int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
    except sqlite3.Error as exc:
        logger.error("Ошибка подсчёта пользователей: %s", exc)
        return 0


def has_admins(db_path: str) -> bool:
    try:
        with connect(db_path) as conn:
            return (
                conn.execute("SELECT 1 FROM users WHERE is_admin = 1 LIMIT 1").fetchone()
                is not None
            )
    except sqlite3.Error as exc:
        logger.error("Ошибка проверки администраторов: %s", exc)
        return False


def set_language(db_path: str, user_id: int, language: str) -> None:
    """Запомнить выбранный язык, чтобы он переживал перезапуск бота."""
    try:
        with connect(db_path) as conn:
            conn.execute(
                "UPDATE users SET language = ? WHERE user_id = ?", (language, user_id)
            )
            conn.commit()
    except sqlite3.Error as exc:
        logger.error("Ошибка сохранения языка %s: %s", user_id, exc)


def get_language(db_path: str, user_id: int, default: str = "ru") -> str:
    try:
        with connect(db_path) as conn:
            row = conn.execute(
                "SELECT language FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        return (row["language"] if row else None) or default
    except sqlite3.Error:
        return default


def touch_profile(
    db_path: str, user_id: int, first_name: str, last_name: str, username: str
) -> None:
    """Обновить имя и username, если человек сменил их в Telegram."""
    add_user(
        db_path,
        user_id,
        first_name=first_name,
        last_name=last_name,
        username=username,
    )


def record_task_metadata(
    db_path: str,
    user_id: int,
    duration_seconds: float,
    original_file_type: str,
    recognized_text: str,
    language: str | None = None,
) -> None:
    try:
        with connect(db_path) as conn:
            conn.execute(
                """INSERT INTO tasks
                   (user_id, timestamp, duration_seconds, original_file_type,
                    recognized_text, language)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    datetime.now().isoformat(timespec="seconds"),
                    duration_seconds,
                    original_file_type,
                    recognized_text,
                    language,
                ),
            )
            conn.commit()
    except sqlite3.Error as exc:
        logger.error("Ошибка записи запроса пользователя %s: %s", user_id, exc)


def get_bot_stats(db_path: str) -> dict:
    """Счётчики для `/stats`: пользователи, запросы за сегодня и за неделю."""
    empty = {
        "total_users": 0,
        "today_active": 0,
        "today_requests": 0,
        "today_new": 0,
        "week_active": 0,
        "week_requests": 0,
        "week_new": 0,
    }
    try:
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=7)
        today_iso = today_start.isoformat(timespec="seconds")
        week_iso = week_start.isoformat(timespec="seconds")

        with connect(db_path) as conn:
            total_users = int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])

            today_active = int(
                conn.execute(
                    "SELECT COUNT(DISTINCT user_id) FROM tasks WHERE timestamp >= ?",
                    (today_iso,),
                ).fetchone()[0]
            )
            today_requests = int(
                conn.execute(
                    "SELECT COUNT(*) FROM tasks WHERE timestamp >= ?", (today_iso,)
                ).fetchone()[0]
            )
            today_new = int(
                conn.execute(
                    "SELECT COUNT(*) FROM users WHERE created_at >= ?", (today_iso,)
                ).fetchone()[0]
            )

            week_active = int(
                conn.execute(
                    "SELECT COUNT(DISTINCT user_id) FROM tasks WHERE timestamp >= ?",
                    (week_iso,),
                ).fetchone()[0]
            )
            week_requests = int(
                conn.execute(
                    "SELECT COUNT(*) FROM tasks WHERE timestamp >= ?", (week_iso,)
                ).fetchone()[0]
            )
            week_new = int(
                conn.execute(
                    "SELECT COUNT(*) FROM users WHERE created_at >= ?", (week_iso,)
                ).fetchone()[0]
            )

        return {
            "total_users": total_users,
            "today_active": today_active,
            "today_requests": today_requests,
            "today_new": today_new,
            "week_active": week_active,
            "week_requests": week_requests,
            "week_new": week_new,
        }
    except sqlite3.Error as exc:
        logger.error("Ошибка чтения статистики: %s", exc)
        return empty
