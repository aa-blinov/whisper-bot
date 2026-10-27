"""Сквозная проверка обработчиков бота без обращений к Telegram.

Подменяет сетевые методы `Bot`, прогоняет настоящие `Update` через
`Application.process_update` и проверяет базу и отправленные сообщения.
Распознавание при этом настоящее: файл уходит в Huey, воркер в соседнем
контейнере возвращает текст. База своя: скрипт создаёт `lazy_smoke`,
поэтому боевые данные не трогает.

Запуск внутри контейнера:
    docker compose cp scripts/smoke_flow.py lazy-to-text-bot:/app/smoke_flow.py
    docker compose exec lazy-to-text-bot python smoke_flow.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

from dotenv import load_dotenv

load_dotenv()

SMOKE_DB = "lazy_smoke"


def _prepare_database() -> str:
    """Отдельная база для проверки: боевую не трогаем."""
    import psycopg

    base = os.environ.get("DATABASE_URL") or "postgresql://lazy:lazy@postgres:5432/lazy"
    server, _, _name = base.rpartition("/")
    with psycopg.connect(f"{server}/postgres", autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {SMOKE_DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {SMOKE_DB}")
    smoke_url = f"{server}/{SMOKE_DB}"
    os.environ["DATABASE_URL"] = smoke_url
    return smoke_url


SMOKE_URL = _prepare_database()
# Проверяем сценарий «админа ещё нет»: первый /start забирает роль.
os.environ["ADMIN_ID"] = ""
os.environ["DATA_DIR"] = "data"
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:SMOKE-TEST-TOKEN")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from telegram import (  # noqa: E402
    Audio,
    Bot,
    Document,
    InlineKeyboardMarkup,
    Update,
    User,
    Video,
    Voice,
)

from app.bot import app as bot_app  # noqa: E402
from app.bot.app import build_application  # noqa: E402
from app.config import Settings  # noqa: E402
from app.container import build_services  # noqa: E402
from app.infra import database  # noqa: E402
from app.services.transcription import TranscriptTooLong, TranscriptionTimeout  # noqa: E402

SAMPLE = os.environ.get("SMOKE_AUDIO", "tests/fixtures/sample.mp3")
SAMPLE_EN = os.environ.get("SMOKE_AUDIO_EN", "tests/fixtures/sample_en.mp3")
SAMPLE_VIDEO = os.environ.get("SMOKE_VIDEO", "tests/fixtures/sample.mp4")
SAMPLE_LONG = os.environ.get("SMOKE_LONG", "tests/fixtures/long.mp3")
ADMIN_ID = 111
GUEST_ID = 222
NEWCOMER_ID = 333
STRANGER_ID = 444

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


def base_message(
    user_id: int, message_id: int, chat_type: str = "private", **extra
) -> dict:
    data = {
        "message_id": message_id,
        "date": 1_700_000_000,
        "chat": {"id": user_id, "type": chat_type},
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
    has_video = os.path.exists(SAMPLE_VIDEO)
    has_english = os.path.exists(SAMPLE_EN)
    has_long = os.path.exists(SAMPLE_LONG)
    missing = [
        path
        for path, present in (
            (SAMPLE, has_audio),
            (SAMPLE_VIDEO, has_video),
            (SAMPLE_EN, has_english),
            (SAMPLE_LONG, has_long),
        )
        if not present
    ]
    if missing:
        # Без образцов проверка прошла бы, не тронув воркер. Лучше упасть.
        print("нет тестовых файлов: " + ", ".join(missing))
        print("они лежат в tests/fixtures и попадают в образ вместе с app/")
        raise SystemExit(2)

    database.init_db(settings.database_url, settings.admin_ids)
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
        ("get_my_name", AsyncMock(return_value=type("N", (), {"name": bot_app.BOT_NAME})())),
        (
            "get_my_description",
            AsyncMock(
                return_value=type("D", (), {"description": bot_app.DESCRIPTION})()
            ),
        ),
        (
            "get_my_short_description",
            AsyncMock(
                return_value=type(
                    "S", (), {"short_description": bot_app.SHORT_DESCRIPTION}
                )()
            ),
        ),
        ("get_me", fake_get_me),
    ):
        stack.enter_context(patch.object(Bot, name, new=mock))

    async def fake_get_file(self, *args, **kwargs):
        """Вместо ссылки Telegram отдаём локальный путь на общем томе."""
        return type("F", (), {"file_path": SAMPLE, "file_size": 69984})()

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
        check(database.get_user(settings.database_url, ADMIN_ID) is not None, "первый допущен")
        check(
            bool(database.get_user(settings.database_url, ADMIN_ID).is_admin),
            "он администратор",
        )
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

        # 2b. В группе админка молчит: иначе список людей видит вся группа.
        print("2b. Админка в группе")
        sent.clear()
        await process(
            {"message": base_message(ADMIN_ID, 3, chat_type="group", text="/admin")}
        )
        check(not any("Админ-панель" in text for text in texts()), "в группе панели нет")
        sent.clear()
        await process(
            {
                "message": base_message(
                    ADMIN_ID,
                    3,
                    chat_type="group",
                    voice={
                        "file_id": "smoke-group",
                        "file_unique_id": "smoke-group-unique",
                        "duration": 3,
                        "mime_type": "audio/ogg",
                        "file_size": 1234,
                    },
                )
            }
        )
        check(not texts(), "в группе медиа игнорируется")

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
        check(
            database.get_user(settings.database_url, GUEST_ID) is not None,
            "пользователь в базе",
        )
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
        check(
            database.get_user(settings.database_url, GUEST_ID) is None,
            "доступ убран",
        )

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
            database.get_user(settings.database_url, NEWCOMER_ID) is not None,
            "заявка одобрена",
        )

        # 6b. Посторонний присылает голосовое: заявка, а не расшифровка.
        print("6b. Медиа без доступа")
        sent.clear()
        stranger_voice = base_message(
            STRANGER_ID,
            21,
            voice={
                "file_id": "smoke-stranger",
                "file_unique_id": "smoke-stranger-unique",
                "duration": 3,
                "mime_type": "audio/ogg",
                "file_size": 1234,
            },
        )
        await process({"message": stranger_voice})
        check(
            any(chat == ADMIN_ID and "Заявка" in text for chat, text, _ in sent),
            "админу ушла заявка",
        )
        check(not any("<pre>" in text for text in texts()), "расшифровки не было")

        # 6c. Не админ не может открыть панель по callback.
        print("6c. Callback без прав")
        sent.clear()
        await process(callback_update(STRANGER_ID, "admin:list"))
        check(
            not any("Админ-панель" in text for text in texts() + edits),
            "панель закрыта",
        )

        # 7. Язык.
        print("7. Язык распознавания")
        sent.clear()
        await process({"message": base_message(ADMIN_ID, 30, text="/language")})
        check(any("язык" in text.lower() for text in texts()), "меню языка показано")
        await process({"message": base_message(ADMIN_ID, 31, text="🇷🇺 Русский")})
        check(
            database.get_user(settings.database_url, ADMIN_ID).language == "ru",
            "язык сохранён в базе",
        )

        # 7b. Английский язык и вторая модель.
        print("7b. Английский язык")
        if has_english:
            sent.clear()
            await process({"message": base_message(ADMIN_ID, 32, text="/language")})
            await process({"message": base_message(ADMIN_ID, 33, text="🇬🇧 Английский")})
            check(
                database.get_user(settings.database_url, ADMIN_ID).language == "en",
                "выбран английский",
            )
            sent.clear()
            english_voice = base_message(
                ADMIN_ID,
                34,
                voice={
                    "file_id": "smoke-en",
                    "file_unique_id": "smoke-en-unique",
                    "duration": 8,
                    "mime_type": "audio/mpeg",
                    "file_size": 50976,
                },
            )
            with patch.object(Voice, "get_file", fake_get_file), patch(
                "app.bot.handlers.media.file_url", lambda ctx, f: SAMPLE_EN
            ):
                await process({"message": english_voice})
            english = [text for text in texts() if "<pre>" in text]
            check(bool(english), "английская расшифровка пришла")
            if english:
                body = english[0].lower()
                print("     " + english[0][:160])
                check(
                    any(ch in body for ch in "abcdefghijklmnopqrstuvwxyz")
                    and "привет" not in body,
                    "текст на английском",
                )
            # Возвращаем русский, дальше сценарий проверяет русскую модель.
            await process({"message": base_message(ADMIN_ID, 35, text="/language")})
            await process({"message": base_message(ADMIN_ID, 36, text="🇷🇺 Русский")})
        else:
            print("  skip  нет английского файла")

        # 8. Голосовое сообщение: ссылка подменена, распознавание настоящее.
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
            with patch.object(Voice, "get_file", fake_get_file), patch(
                "app.bot.handlers.media.file_url", lambda ctx, f: SAMPLE
            ):
                await process({"message": voice_message})

            transcript = [text for text in texts() if "<pre>" in text]
            check(bool(transcript), "ответ с расшифровкой отправлен")
            if transcript:
                body = transcript[0]
                print("     " + body[:200])
                check("Привет" in body, "текст распознан")
                check("." in body and "," in body, "пунктуация на месте")
            check(
                database.stats(settings.database_url).today_requests >= 1,
                "запрос записан в историю",
            )
        else:
            print("  skip  нет файла для распознавания")

        # 9. Аудиофайл как audio (не document).
        print("9. Аудиофайл как audio")
        if has_audio:
            sent.clear()
            audio_message = base_message(
                ADMIN_ID,
                50,
                audio={
                    "file_id": "smoke-audio",
                    "file_unique_id": "smoke-audio-unique",
                    "duration": 12,
                    "mime_type": "audio/mpeg",
                    "file_size": 69984,
                },
            )
            with patch.object(Audio, "get_file", fake_get_file), patch(
                "app.bot.handlers.media.file_url", lambda ctx, f: SAMPLE
            ):
                await process({"message": audio_message})
            check(
                any("<pre>" in text and "Привет" in text for text in texts()),
                "audio распознан",
            )
        else:
            print("  skip  нет файла")

        # 10. Аудиофайл документом: mp3 приходит как document.
        print("10. MP3 документом")
        if has_audio:
            sent.clear()
            document_message = base_message(
                ADMIN_ID,
                60,
                document={
                    "file_id": "smoke-doc",
                    "file_unique_id": "smoke-doc-unique",
                    "file_name": "note.mp3",
                    "mime_type": "audio/mpeg",
                    "file_size": 69984,
                },
            )
            with patch.object(Document, "get_file", fake_get_file), patch(
                "app.bot.handlers.media.file_url", lambda ctx, f: SAMPLE
            ):
                await process({"message": document_message})
            check(
                any("<pre>" in text and "Привет" in text for text in texts()),
                "mp3-документ распознан",
            )
        else:
            print("  skip  нет файла")

        # 11. Видеофайл: дорожку достаёт ffmpeg.
        print("11. Видеофайл")
        if has_video:
            sent.clear()
            video_message = base_message(
                ADMIN_ID,
                65,
                video={
                    "file_id": "smoke-video",
                    "file_unique_id": "smoke-video-unique",
                    "duration": 12,
                    "width": 320,
                    "height": 240,
                    "mime_type": "video/mp4",
                    "file_size": 69984,
                },
            )
            with patch.object(Video, "get_file", fake_get_file), patch(
                "app.bot.handlers.media.file_url", lambda ctx, f: SAMPLE_VIDEO
            ):
                await process({"message": video_message})
            check(
                any("<pre>" in text and "Привет" in text for text in texts()),
                "видео распознано",
            )
        else:
            print("  skip  нет видео")

        # 12. Не медиа документом: понятный отказ, без распознавания.
        print("12. PDF документом")
        sent.clear()
        pdf_message = base_message(
            ADMIN_ID,
            70,
            document={
                "file_id": "smoke-pdf",
                "file_unique_id": "smoke-pdf-unique",
                "file_name": "report.pdf",
                "mime_type": "application/pdf",
                "file_size": 1234,
            },
        )
        await process({"message": pdf_message})
        check(any("не похоже" in text.lower() for text in texts()), "PDF отклонён")

        # 13. Файл больше лимита: отказ до запроса к Telegram.
        print("13. Файл больше 20 МБ")
        sent.clear()
        big_message = base_message(
            ADMIN_ID,
            80,
            audio={
                "file_id": "smoke-big",
                "file_unique_id": "smoke-big-unique",
                "duration": 100,
                "mime_type": "audio/mpeg",
                "file_size": 25 * 1024 * 1024,
            },
        )
        await process({"message": big_message})
        check(any("20 МБ" in text for text in texts()), "большой файл отклонён")

        # 13b. Слишком длинная запись: отказ до очереди.
        print("13b. Запись длиннее лимита")
        sent.clear()
        long_message = base_message(
            ADMIN_ID,
            85,
            audio={
                "file_id": "smoke-long",
                "file_unique_id": "smoke-long-unique",
                "duration": 400,
                "mime_type": "audio/mpeg",
                "file_size": 1024,
            },
        )
        await process({"message": long_message})
        check(any("Запись длится" in text for text in texts()), "длинная запись отклонена")

        # 14. Удаление человека не стирает историю.
        print("14. Удаление сохраняет историю")
        database.record_task(
            settings.database_url, NEWCOMER_ID, 1.0, "voice", "история после удаления", "ru"
        )
        with database.connect(settings.database_url) as conn:
            before = conn.execute(
                "SELECT COUNT(*) AS n FROM tasks WHERE recognized_text = %s",
                ("история после удаления",),
            ).fetchone()["n"]
        removed = database.remove_user(settings.database_url, NEWCOMER_ID)
        with database.connect(settings.database_url) as conn:
            after = conn.execute(
                "SELECT COUNT(*) AS n FROM tasks WHERE recognized_text = %s",
                ("история после удаления",),
            ).fetchone()["n"]
            orphan = conn.execute(
                """SELECT COUNT(*) AS n FROM tasks
                   WHERE recognized_text = %s AND user_id IS NULL""",
                ("история после удаления",),
            ).fetchone()["n"]
        check(bool(removed), "пользователь удалён")
        check(database.get_user(settings.database_url, NEWCOMER_ID) is None, "доступа больше нет")
        check(before == after == 1 and orphan == 1, "строка истории осталась без владельца")

        # 15. Посторонний текст не ломает бота.
        print("15. Посторонний текст")
        sent.clear()
        await process({"message": base_message(ADMIN_ID, 90, text="просто текст")})
        check(
            any("голосовое" in text.lower() for text in texts()),
            "бот объяснил, что прислать",
        )

        # 15b. Длинный текст режется, спецсимволы экранируются.
        print("15b. Длинный текст и экранирование")
        from app.bot.formatting import escape, transcript_blocks

        blocks = transcript_blocks("строка с <тегом> " * 600)
        check(len(blocks) > 1, "длинный текст разбит на части")
        check(all(len(block) < 4096 for block in blocks), "каждая часть короче лимита")
        check(all("<pre>" in block and "</pre>" in block for block in blocks), "каждая часть в pre")
        check(escape("<b>&") == "&lt;b&gt;&amp;", "HTML экранируется")

        # 16. Таймаут воркера показывает понятный текст, а не падает.
        print("16. Таймаут распознавания")
        sent.clear()
        service = application.bot_data["transcription"]
        timeout_voice = base_message(
            ADMIN_ID,
            95,
            voice={
                "file_id": "smoke-timeout",
                "file_unique_id": "smoke-timeout-unique",
                "duration": 5,
                "mime_type": "audio/ogg",
                "file_size": 1234,
            },
        )
        with patch.object(Voice, "get_file", fake_get_file), patch(
            "app.bot.handlers.media.file_url", lambda ctx, f: SAMPLE
        ), patch.object(
            service, "transcribe", AsyncMock(side_effect=TranscriptionTimeout("тест"))
        ):
            await process({"message": timeout_voice})
        check(any("затянулось" in text for text in texts()), "таймаут объяснён")

        # 16b. Слишком длинный документ, поймано воркером.
        print("16b. Документ длиннее лимита")
        sent.clear()
        with patch.object(Voice, "get_file", fake_get_file), patch(
            "app.bot.handlers.media.file_url", lambda ctx, f: SAMPLE
        ), patch.object(
            service,
            "transcribe",
            AsyncMock(side_effect=TranscriptTooLong(400)),
        ):
            await process({"message": timeout_voice})
        check(any("Запись длится 400" in text for text in texts()), "длина объяснена")
        # 16c. Ссылка не попадает в лог, лимит длины проверяет воркер.
        print("16c. Токен в логах и лимит длины")
        from app.infra.asr import Recognizer, _scrub

        check(
            "SECRET" not in _scrub("https://api.telegram.org/file/bot1:SECRET/x.mp3"),
            "токен вырезан из текста ошибки",
        )
        if has_long:
            recognizer = Recognizer(
                settings.asr_model,
                settings.asr_model_en,
                settings.asr_quantization,
                settings.asr_threads,
            )
            text, lang, too_long = recognizer.transcribe_source(
                SAMPLE_LONG, language="ru", max_seconds=30
            )
            check(text is None and lang is None, "текста нет")
            check(bool(too_long) and too_long > 30, "воркер вернул длительность")
        else:
            print("  skip  нет длинного файла")

        # 17. Гонка за первого администратора: ровно один.
        print("17. Гонка за первого админа")
        with database.connect(settings.database_url) as conn:
            conn.execute("DELETE FROM users")
        results: list[bool] = []

        def claim(user_id: int) -> None:
            results.append(database.claim_first_admin(settings.database_url, user_id))

        threads = [
            threading.Thread(target=claim, args=(user_id,)) for user_id in (501, 502)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        admins = [user for user in database.list_users(settings.database_url) if user.is_admin]
        check(sum(1 for value in results if value) == 1, "права получил ровно один")
        check(len(admins) == 1, "админ в базе один")
    finally:
        await application.shutdown()
        stack.close()
        database.close_all()

    print()
    if failures:
        print(f"ПРОВАЛЕНО: {len(failures)}")
        for item in failures:
            print(f" - {item}")
        raise SystemExit(1)
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")


if __name__ == "__main__":
    asyncio.run(run())
