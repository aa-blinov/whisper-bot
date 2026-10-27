"""Одноразовый перенос истории из старой SQLite в Postgres.

    python scripts/import_sqlite.py [--sqlite data/bot_database.db]
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Settings  # noqa: E402
from app.infra import database  # noqa: E402


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", default="data/bot_database.db")
    args = parser.parse_args()

    if not os.path.exists(args.sqlite):
        print(f"нет файла {args.sqlite}: переносить нечего")
        return 0

    settings = Settings.from_env()
    database.init_db(settings.database_url, settings.admin_ids)

    source = sqlite3.connect(args.sqlite)
    source.row_factory = sqlite3.Row
    users = source.execute("SELECT * FROM users").fetchall()
    tasks = source.execute("SELECT * FROM tasks").fetchall()

    imported_users = 0
    for row in users:
        database.add_user(
            settings.database_url,
            int(row["user_id"]),
            is_admin=bool(row["is_admin"]),
            first_name=row["first_name"] or "",
            last_name=row["last_name"] or "",
            username=row["username"] or "",
        )
        imported_users += 1

    imported_tasks = 0
    with database.connect(settings.database_url) as conn:
        for row in tasks:
            user_id = row["user_id"]
            if user_id is not None:
                exists = conn.execute(
                    "SELECT 1 FROM users WHERE user_id = %s", (int(user_id),)
                ).fetchone()
                if not exists:
                    user_id = None
            conn.execute(
                """INSERT INTO tasks
                   (user_id, timestamp, duration_seconds, original_file_type,
                    recognized_text, language)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (
                    int(user_id) if user_id is not None else None,
                    parse_time(row["timestamp"]) or datetime.now(),
                    row["duration_seconds"],
                    row["original_file_type"],
                    row["recognized_text"],
                    row["language"] if "language" in row.keys() else None,
                ),
            )
            imported_tasks += 1

    source.close()
    database.close_all()
    print(f"перенесено: пользователей {imported_users}, запросов {imported_tasks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
