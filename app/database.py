import logging
import os
import sqlite3

from datetime import datetime

logger = logging.getLogger(__name__)


def init_db(db_name: str) -> None:
    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                is_admin BOOLEAN DEFAULT FALSE
            )
            """
        )
        cursor.execute("PRAGMA table_info(users)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        for col, coltype in [
            ("first_name", "TEXT"),
            ("last_name", "TEXT"),
            ("username", "TEXT")
        ]:
            if col not in existing_cols:
                try:
                    cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {coltype}")
                except sqlite3.OperationalError as e:
                    logger.warning(f"Ошибка миграции users: {e}")

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                duration_seconds REAL,
                original_file_type TEXT,
                recognized_text TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
            """
        )
        conn.commit()

        admin_id_str = os.getenv("ADMIN_ID")
        if admin_id_str:
            admin_id = int(admin_id_str)
            cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (admin_id,))
            if cursor.fetchone() is None:
                cursor.execute(
                    "INSERT INTO users (user_id, is_admin) VALUES (?, ?)",
                    (admin_id, True),
                )
                conn.commit()
                logger.info(f"Администратор с ID {admin_id} добавлен в базу данных.")
        else:
            logger.warning(
                "Переменная окружения ADMIN_ID не установлена. Администратор не будет добавлен автоматически."
            )

        conn.close()
        logger.info(f"База данных '{db_name}' успешно инициализирована.")
    except sqlite3.Error as e:
        logger.error(f"Ошибка инициализации базы данных: {e}")


def add_user(
    db_name: str,
    user_id: int,
    is_admin: bool = False,
    first_name: str = "",
    last_name: str = "",
    username: str = "",
) -> None:
    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO users (user_id, is_admin, first_name, last_name, username) VALUES (?, ?, ?, ?, ?)",
            (user_id, is_admin, first_name, last_name, username),
        )
        conn.commit()
        conn.close()
        logger.info(f"Пользователь {user_id} добавлен/обновлен в БД.")
    except sqlite3.Error as e:
        logger.error(f"Ошибка при добавлении пользователя {user_id}: {e}")


def remove_user(db_name: str, user_id: int) -> None:
    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        logger.info(f"Пользователь {user_id} удален из БД.")
    except sqlite3.Error as e:
        logger.error(f"Ошибка при удалении пользователя {user_id}: {e}")


def is_user_allowed(db_name: str, user_id: int) -> bool:
    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result is not None
    except sqlite3.Error as e:
        logger.error(f"Ошибка при проверке доступа пользователя {user_id}: {e}")
        return False


def get_all_users(db_name: str) -> list[tuple[int, bool, str, str, str]]:
    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, is_admin, first_name, last_name, username FROM users")
        users = cursor.fetchall()
        conn.close()
        return users
    except sqlite3.Error as e:
        logger.error(f"Ошибка при получении списка пользователей: {e}")
        return []


def record_task_metadata(
    db_name: str,
    user_id: int,
    duration_seconds: float,
    original_file_type: str,
    recognized_text: str,
) -> None:
    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        timestamp = datetime.now().isoformat()
        cursor.execute(
            """
            INSERT INTO tasks (user_id, timestamp, duration_seconds, original_file_type, recognized_text)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, timestamp, duration_seconds, original_file_type, recognized_text),
        )
        conn.commit()
        conn.close()
        logger.info(f"Метаданные задачи для пользователя {user_id} записаны в БД.")
    except sqlite3.Error as e:
        logger.error(
            f"Ошибка при записи метаданных задачи для пользователя {user_id}: {e}"
        )
