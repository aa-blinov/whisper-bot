"""Сквозная проверка обработчиков бота без обращений к Telegram.

Подменяет сетевые методы `Bot`, прогоняет настоящие `Update` через
`Application.process_update` и проверяет базу и отправленные сообщения.
Распознавание при этом настоящее: файл уходит в Huey, воркер в соседнем
контейнере возвращает текст.

Запуск внутри контейнера:
    docker compose cp scripts/smoke_flow.py telegram-stt-bot:/app/smoke_flow.py
    docker compose exec telegram-stt-bot python smoke_flow.py
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

os.environ["DB_PATH"] = "data/smoke.db"
os.environ["DATA_DIR"] = "data"
# Проверяем сценарий «админа ещё нет»: первый /start забирает роль.
os.environ["ADMIN_ID"] = ""
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:SMOKE-TEST-TOKEN")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from telegram import Bot, InlineKeyboardMarkup, Update, User, Voice  # noqa: E402

from app.bot.app import build_application  # noqa: E402
from app.config import Settings  # noqa: E402
from app.container import build_services  # noqa: E402
from app.infra import database  # noqa: E402

SAMPLE = os.environ.get("SMOKE_AUDIO", "data/_test/sample.mp3")
ADMIN_ID = 111
GUEST_ID = 222
NEWCOMER_ID = 333

sent: list[tuple[int | None, str, object]] = []
edits: list[str] = []
failures: list[str] = []

settings = Settings.from_env()


class FakeMessage:
    def __init__(self, message_id: int = 1) -> None:
        self.message_id = message_id

    async def edit_text(self, *args, **kwargs):
        text = args[0] if args else kwargs.get("text", "")
        edits.append(str(text))
        sent.append((None, f"EDIT {text}", kwargs.get("reply_markup")))
        return self

    async def delete(self):
        return True


def check(condition: bool, label: str) -> None:
    print(("  ok   " if condition else "  FAIL ") + label)
    if not condition:
        failures.append(label)


def texts() -> list[str]:
    return [text for _, text, _ in sent]


def markups() -> list[object]:
    return [markup for _, _, markup in sent]


def base_message(user_id: int, message_id: int, **extra) -> dict:
    data = {
        "message_id": message_id,
        "date": 1_700_000_000,
        "chat": {"id": user_id, "type": "private"},
        "from": {
            "id": user_id,
            "is_bot": False,
            "first_name": f"Тест{user_id}",
            "username": f"test{user_id}",
        },
    }
    data.update(extra)
    text = data.get("text")
    if isinstance(text, str) and text.startswith("/"):
        command = text.split()[0]
        data["entities"] = [{"type": "bot_command", "offset": 0, "length": len(command)}]
    return data


def callback_update(user_id: int, data: str) -> dict:
    return {
        "update_id": 0,
        "callback_query": {
            "id": f"cb-{data}",
            "from": {
                "id": user_id,
                "is_bot": False,
                "first_name": f"Тест{user_id}",
                "username": f"test{user_id}",
            },
            "message": base_message(user_id, 900, text="панель"),
            "chat_instance": "1",
            "data": data,
        },
    }


async def run() -> None:
    has_audio = os.path.exists(SAMPLE)
    if not has_audio:
        print(f"нет файла {SAMPLE}: шаг с распознаванием будет пропущен")

    # Прогон должен быть повторяемым: иначе пользователи из прошлого
    # запуска делают проверки заявки и списка ложно-красными.
    try:
        os.remove(settings.db_path)
    except FileNotFoundError:
        pass

    database.init_db(settings.db_path, settings.admin_ids)
    application = build_application(settings, build_services(settings))
    bot = application.bot
    update_id = 0

    async def fake_send_message(*args, **kwargs):
        chat_id = kwargs.get("chat_id", args[0] if args else None)
        text = kwargs.get("text", args[1] if len(args) > 1 else "")
        sent.append((chat_id, str(text), kwargs.get("reply_markup")))
        return FakeMessage(message_id=len(sent) + 1)

    async def fake_edit_message_text(*args, **kwargs):
        text = kwargs.get("text", args[2] if len(args) > 2 else "")
        edits.append(str(text))
        return True

    async def fake_get_me(self, *args, **kwargs):
        """Подмена get_me: PTB запоминает пользователя только на этом вызове."""
        user = User(id=999, is_bot=True, first_name="SmokeBot", username="smoke_bot")
        self._bot_user = user
        return user

    # `Bot` — наследник TelegramObject, атрибуты экземпляра не присвоить,
    # поэтому подменяем методы класса.
    stack = ExitStack()
    for name, mock in (
        ("send_message", AsyncMock(side_effect=fake_send_message)),
        ("edit_message_text", AsyncMock(side_effect=fake_edit_message_text)),
        ("delete_message", AsyncMock(return_value=True)),
        ("send_chat_action", AsyncMock(return_value=True)),
        ("get_chat", AsyncMock(side_effect=Exception("нет доступа к профилю"))),
        ("set_my_commands", AsyncMock(return_value=True)),
        ("set_my_short_description", AsyncMock(return_value=True)),
        ("set_my_name", AsyncMock(return_value=True)),
        ("set_my_description", AsyncMock(return_value=True)),
        ("get_user_profile_photos", AsyncMock(return_value=type("P", (), {"total_count": 1})())),
        ("set_my_profile_photo", AsyncMock(return_value=True)),
        ("get_me", fake_get_me),
    ):
        stack.enter_context(patch.object(Bot, name, new=mock))

    async def fake_get_file(self, *args, **kwargs):
        class FakeFile:
            async def download_to_drive(self, custom_path=None, *a, **k):
                shutil.copy(SAMPLE, custom_path)
                return custom_path

        return FakeFile()

    await application.initialize()

    async def process(data: dict) -> None:
        nonlocal update_id
        update_id += 1
        data["update_id"] = update_id
        await application.process_update(Update.de_json(data, bot))

    try:
        # 1. Первый /start становится админом.
        print("1. /start без ADMIN_ID")
        await process({"message": base_message(ADMIN_ID, 1, text="/start")})
        check(database.get_user(settings.db_path, ADMIN_ID) is not None, "первый допущен")
        check(bool(database.get_user(settings.db_path, ADMIN_ID).is_admin), "он администратор")
        check(any("Привет" in text for text in texts()), "пришло приветствие")

        # 2. Панель с inline-кнопками.
        print("2. /admin")
        sent.clear()
        await process({"message": base_message(ADMIN_ID, 2, text="/admin")})
        check(any("Админ-панель" in text for text in texts()), "панель отправлена")
        check(
            any(isinstance(markup, InlineKeyboardMarkup) for markup in markups()),
            "панель с inline-кнопками",
        )

        # 3. Добавление по числовому ID через диалог.
        print("3. Добавление по числовому ID")
        sent.clear()
        await process(callback_update(ADMIN_ID, "admin:add"))
        check(
            any("Кого добавить" in text for text in texts() + edits),
            "бот спросил, кого добавить",
        )
        await process({"message": base_message(ADMIN_ID, 4, text=str(GUEST_ID))})
        check(any("Добавить этого человека" in text for text in texts()), "пришла карточка")
        await process(callback_update(ADMIN_ID, f"add:{GUEST_ID}"))
        check(database.get_user(settings.db_path, GUEST_ID) is not None, "пользователь в базе")
        check(
            any(chat == GUEST_ID for chat, _, _ in sent),
            "новому пользователю отправлено приветствие",
        )

        # 4. Список и карточка.
        print("4. Список и карточка")
        sent.clear()
        await process({"message": base_message(ADMIN_ID, 6, text="/users")})
        check(any(str(GUEST_ID) in text for text in texts()), "ID виден в списке")
        edits.clear()
        await process(callback_update(ADMIN_ID, f"user:{GUEST_ID}"))
        check(any("ID:" in text for text in edits), "карточка открылась")

        # 5. Удаление доступа.
        print("5. Удаление доступа")
        await process(callback_update(ADMIN_ID, f"user:{GUEST_ID}:del"))
        await process(callback_update(ADMIN_ID, f"user:{GUEST_ID}:del:yes"))
        check(database.get_user(settings.db_path, GUEST_ID) is None, "доступ убран")

        # 6. Заявка от нового человека и разрешение одним нажатием.
        print("6. Заявка на доступ")
        sent.clear()
        await process({"message": base_message(NEWCOMER_ID, 20, text="/start")})
        check(
            any(chat == ADMIN_ID and "Заявка" in text for chat, text, _ in sent),
            "админу пришла заявка",
        )
        await process(callback_update(ADMIN_ID, f"req:{NEWCOMER_ID}:allow"))
        check(
            database.get_user(settings.db_path, NEWCOMER_ID) is not None,
            "заявка одобрена",
        )

        # 7. Язык.
        print("7. Язык распознавания")
        sent.clear()
        await process({"message": base_message(ADMIN_ID, 30, text="/language")})
        check(any("язык" in text.lower() for text in texts()), "меню языка показано")
        await process({"message": base_message(ADMIN_ID, 31, text="🇷🇺 Русский")})
        check(
            database.get_user(settings.db_path, ADMIN_ID).language == "ru",
            "язык сохранён в базе",
        )

        # 8. Голосовое сообщение: скачивание подменено, распознавание настоящее.
        print("8. Голосовое сообщение → текст (настоящий воркер)")
        if has_audio:
            sent.clear()
            voice_message = base_message(
                ADMIN_ID,
                40,
                voice={
                    "file_id": "smoke-file",
                    "file_unique_id": "smoke-unique",
                    "duration": 12,
                    "mime_type": "audio/ogg",
                    "file_size": 69984,
                },
            )
            with patch.object(Voice, "get_file", fake_get_file):
                await process({"message": voice_message})

            transcript = [text for text in texts() if "<pre>" in text]
            check(bool(transcript), "ответ с расшифровкой отправлен")
            if transcript:
                body = transcript[0]
                print("     " + body[:200])
                check("Привет" in body, "текст распознан")
                check("." in body and "," in body, "пунктуация на месте")
            check(
                database.stats(settings.db_path).today_requests >= 1,
                "запрос записан в историю",
            )
        else:
            print("  skip  нет файла для распознавания")

        # 9. Посторонний текст не ломает бота.
        print("9. Посторонний текст")
        sent.clear()
        await process({"message": base_message(ADMIN_ID, 50, text="просто текст")})
        check(
            any("голосовое" in text.lower() for text in texts()),
            "бот объяснил, что прислать",
        )
    finally:
        await application.shutdown()
        stack.close()

    print()
    if failures:
        print(f"ПРОВАЛЕНО: {len(failures)}")
        for item in failures:
            print(f" - {item}")
        raise SystemExit(1)
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")


if __name__ == "__main__":
    asyncio.run(run())
