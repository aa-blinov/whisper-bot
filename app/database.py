import logging
import os
import sqlite3

from datetime import datetime, timedelta

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


def get_bot_stats(db_name: str) -> dict:
    """
    Получить статистику бота.
    Возвращает словарь с данными:
    - total_users: всего пользователей
    - today_active: активных сегодня (уникальных пользователей с задачами)
    - today_requests: запросов на STT сегодня
    - today_new: новых пользователей сегодня
    - week_active: активных за последние 7 дней
    - week_requests: запросов на STT за последние 7 дней
    - week_new: новых пользователей за последние 7 дней
    """
    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        
        # Получаем текущую дату и дату начала дня
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = week_start - timedelta(days=7)
        
        today_start_str = today_start.isoformat()
        week_start_str = week_start.isoformat()
        now_str = now.isoformat()
        
        # Всего пользователей
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        
        # Статистика за сегодня
        cursor.execute(
            """
            SELECT COUNT(DISTINCT user_id) 
            FROM tasks 
            WHERE timestamp >= ? AND timestamp <= ?
            """,
            (today_start_str, now_str)
        )
        today_active = cursor.fetchone()[0]
        
        cursor.execute(
            """
            SELECT COUNT(*) 
            FROM tasks 
            WHERE timestamp >= ? AND timestamp <= ?
            """,
            (today_start_str, now_str)
        )
        today_requests = cursor.fetchone()[0]
        
        # Новые пользователи сегодня (нужно проверить, когда пользователь был добавлен)
        # Так как у нас нет поля created_at в users, будем считать новыми тех,
        # у кого первая задача была сегодня
        cursor.execute(
            """
            SELECT COUNT(DISTINCT user_id)
            FROM tasks t1
            WHERE t1.timestamp >= ? AND t1.timestamp <= ?
            AND NOT EXISTS (
                SELECT 1 FROM tasks t2 
                WHERE t2.user_id = t1.user_id 
                AND t2.timestamp < ?
            )
            """,
            (today_start_str, now_str, today_start_str)
        )
        today_new = cursor.fetchone()[0]
        
        # Статистика за последние 7 дней
        cursor.execute(
            """
            SELECT COUNT(DISTINCT user_id) 
            FROM tasks 
            WHERE timestamp >= ? AND timestamp <= ?
            """,
            (week_start_str, now_str)
        )
        week_active = cursor.fetchone()[0]
        
        cursor.execute(
            """
            SELECT COUNT(*) 
            FROM tasks 
            WHERE timestamp >= ? AND timestamp <= ?
            """,
            (week_start_str, now_str)
        )
        week_requests = cursor.fetchone()[0]
        
        # Новые пользователи за последние 7 дней
        cursor.execute(
            """
            SELECT COUNT(DISTINCT user_id)
            FROM tasks t1
            WHERE t1.timestamp >= ? AND t1.timestamp <= ?
            AND NOT EXISTS (
                SELECT 1 FROM tasks t2 
                WHERE t2.user_id = t1.user_id 
                AND t2.timestamp < ?
            )
            """,
            (week_start_str, now_str, week_start_str)
        )
        week_new = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            "total_users": total_users,
            "today_active": today_active,
            "today_requests": today_requests,
            "today_new": today_new,
            "week_active": week_active,
            "week_requests": week_requests,
            "week_new": week_new,
        }
    except sqlite3.Error as e:
        logger.error(f"Ошибка при получении статистики: {e}")
        return {
            "total_users": 0,
            "today_active": 0,
            "today_requests": 0,
            "today_new": 0,
            "week_active": 0,
            "week_requests": 0,
            "week_new": 0,
        }
