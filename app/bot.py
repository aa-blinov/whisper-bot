import asyncio
import logging
import os
import time
import uuid

from dotenv import load_dotenv

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from huey.contrib.asyncio import aget_result

import database
import llm
from huey_tasks import transcribe_task

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
if ADMIN_ID is not None:
    try:
        ADMIN_ID = int(ADMIN_ID)
    except Exception:
        ADMIN_ID = None
DB_PATH = os.getenv("DB_PATH", "data/bot_database.db")

database.init_db(DB_PATH)


def get_admin_keyboard() -> ReplyKeyboardMarkup:
    """Получить клавиатуру для административных команд с кнопкой выбора языка."""
    keyboard = [
        [
            KeyboardButton("Язык"),
            KeyboardButton("Список пользователей"),
        ],
        [
            KeyboardButton("Добавить пользователя"),
            KeyboardButton("Удалить пользователя"),
        ],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)


def get_language_keyboard(current_lang: str = "ru") -> ReplyKeyboardMarkup:
    """Получить клавиатуру для выбора языка с пометкой текущего языка."""
    ru_label = "Русский"
    en_label = "Английский"
    if current_lang == "ru":
        ru_label += " (выбран)"
    elif current_lang == "en":
        en_label += " (выбран)"
    keyboard = [[KeyboardButton(ru_label)], [KeyboardButton(en_label)]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)


def get_user_keyboard() -> ReplyKeyboardMarkup:
    """Получить клавиатуру для обычных пользователей с кнопкой выбора языка."""
    keyboard = [[KeyboardButton("Язык")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa
    """Обработчик команды /start."""
    user = update.effective_user
    user_id = user.id if user else None
    user_name = user.full_name if user else "Пользователь"

    if user_id is not None and database.is_user_allowed(DB_PATH, user_id):
        if ADMIN_ID is not None and user_id == ADMIN_ID:
            if update.message:
                await update.message.reply_text(
                    f"Привет, {user_name}! Я готов конвертировать твои голосовые сообщения и видео-кружки в текст. "
                    "Ты – администратор, поэтому у тебя есть доступ к дополнительным командам.",
                    reply_markup=get_admin_keyboard(),
                )
        else:
            if update.message:
                await update.message.reply_text(
                    f"Привет, {user_name}! Я готов конвертировать твои голосовые сообщения и видео-кружки в текст. "
                    "Просто отправь мне их!",
                    reply_markup=get_user_keyboard(),
                )
    else:
        if update.message:
            await update.message.reply_text(
                f"Привет, {user_name}! К сожалению, у тебя нет доступа к этому боту. "
                "Пожалуйста, свяжись с администратором, чтобы получить доступ."
            )


async def admin_menu_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE  # noqa
) -> None:
    """Обработчик команды /admin_menu для доступа к административным функциям."""
    user = update.effective_user
    user_id = user.id if user else None
    if ADMIN_ID is None or user_id != ADMIN_ID:
        if update.message:
            await update.message.reply_text(
                "Извини, эта команда доступна только администратору."
            )
        return
    if update.message:
        await update.message.reply_text(
            "Добро пожаловать в панель администратора! Выбери команду:",
            reply_markup=get_admin_keyboard(),
        )


async def add_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /add_user для добавления пользователя."""
    user = update.effective_user
    user_id = user.id if user else None
    if ADMIN_ID is None or user_id != ADMIN_ID:
        if update.message:
            await update.message.reply_text(
                "Извини, эта команда доступна только администратору."
            )
        return

    if not hasattr(context, "user_data") or context.user_data is None:
        context.user_data = {}
    context.user_data["admin_action"] = "add"

    if update.message:
        await update.message.reply_text(
            "Пожалуйста, введите ID пользователя, которого нужно добавить.",
            reply_markup=None,
        )
    return


async def remove_user_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Обработчик команды /remove_user для удаления пользователя."""
    user = update.effective_user
    user_id = user.id if user else None
    if ADMIN_ID is None or user_id != ADMIN_ID:
        if update.message:
            await update.message.reply_text(
                "Извини, эта команда доступна только администратору."
            )
        return

    if not hasattr(context, "user_data") or context.user_data is None:
        context.user_data = {}
    context.user_data["admin_action"] = "remove"

    if not context.args:
        users = database.get_all_users(DB_PATH)
        if not users:
            if update.message:
                await update.message.reply_text(
                    "Список разрешённых пользователей пуст."
                )
            return
        message_text = "Список разрешённых пользователей:\n\n"
        keyboard = []
        for u_id, is_admin_flag in users:
            status = " (Админ)" if is_admin_flag else ""
            message_text += f"- `{u_id}`{status}\n"
            if not is_admin_flag:
                keyboard.append([KeyboardButton(str(u_id))])
        message_text += "\nПожалуйста, выберите пользователя для удаления, нажав на кнопку с его ID."
        if update.message:
            await update.message.reply_text(
                message_text,
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardMarkup(
                    keyboard, resize_keyboard=True, one_time_keyboard=True
                ),
            )
        return

    try:
        user_to_remove_id = int(context.args[0])
        database.remove_user(DB_PATH, user_to_remove_id)
        if update.message:
            await update.message.reply_text(
                f"Пользователь с ID `{user_to_remove_id}` успешно удалён из списка разрешённых.",
                parse_mode="Markdown",
                reply_markup=get_admin_keyboard(),
            )
    except ValueError:
        if update.message:
            await update.message.reply_text(
                "Неверный формат ID пользователя. Пожалуйста, используйте только цифры."
            )
    except Exception:
        logger.exception("Ошибка при удалении пользователя:")
        if update.message:
            await update.message.reply_text(
                "Произошла ошибка при удалении пользователя. Попробуйте ещё раз.",
                reply_markup=get_admin_keyboard(),
            )


async def list_users_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Обработчик команды /list_users для отображения списка пользователей."""
    user = update.effective_user
    user_id = user.id if user else None
    if ADMIN_ID is None or user_id != ADMIN_ID:
        if update.message:
            await update.message.reply_text(
                "Извини, эта команда доступна только администратору."
            )
        return

    users = database.get_all_users(DB_PATH)
    if not users:
        if update.message:
            await update.message.reply_text("Список разрешенных пользователей пуст.")
        return

    message_text = "Список разрешенных пользователей: \n\n"
    for u_id, is_admin_flag, first_name, last_name, username in users:
        status = " (Админ)" if is_admin_flag else ""
        name = f"{first_name or ''} {last_name or ''}".strip()
        username_str = f" (@{username})" if username else ""
        if name or username_str:
            message_text += f"- `{u_id}`{status} — {name}{username_str}\n"
        else:
            message_text += f"- `{u_id}`{status}\n"
    if update.message:
        await update.message.reply_text(message_text, parse_mode="Markdown")


async def handle_language_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /language для выбора языка распознавания."""
    current_lang = "ru"
    if hasattr(context, "user_data") and context.user_data is not None:
        current_lang = context.user_data.get("lang", "ru")
    if update.message:
        await update.message.reply_text(
            f"Пожалуйста, выберите язык для распознавания (текущий: {'Русский' if current_lang == 'ru' else 'Английский'}):",
            reply_markup=get_language_keyboard(current_lang),
        )


async def handle_language_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик выбора языка пользователем."""
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip().lower()
    if not hasattr(context, "user_data") or context.user_data is None:
        context.user_data = {}
    is_admin = False
    user = update.effective_user
    user_id = user.id if user else None
    if ADMIN_ID is not None and user_id == ADMIN_ID:
        is_admin = True
    if "англ" in text:
        context.user_data["lang"] = "en"
        await update.message.reply_text(
            "Выбран английский язык. Теперь отправьте голосовое сообщение или видео-кружок.",
            reply_markup=get_admin_keyboard() if is_admin else get_user_keyboard(),
        )
    elif "рус" in text:
        context.user_data["lang"] = "ru"
        await update.message.reply_text(
            "Выбран русский язык. Теперь отправьте голосовое сообщение или видео-кружок.",
            reply_markup=get_admin_keyboard() if is_admin else get_user_keyboard(),
        )
    else:
        current_lang = context.user_data.get("lang", "ru")
        await update.message.reply_text(
            "Пожалуйста, выберите язык с помощью кнопок ниже.",
            reply_markup=get_language_keyboard(current_lang),
        )


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик получения голосовых сообщений и видео-кружков."""
    user = update.effective_user
    user_id = user.id if user else None

    if user_id is None or not database.is_user_allowed(DB_PATH, user_id):
        if update.message:
            await update.message.reply_text(
                "Извини, у тебя нет доступа для отправки медиа. Пожалуйста, свяжись с администратором."
            )
        return

    if not hasattr(context, "user_data") or context.user_data is None:
        context.user_data = {}
    language = context.user_data.get("lang", "ru")

    file_obj = None
    file_type: str = ""
    msg = update.message
    if msg:
        if getattr(msg, "forward_origin", None):
            if getattr(msg, "voice", None):
                file_obj = msg.voice
                file_type = "voice"
            elif getattr(msg, "video_note", None):
                file_obj = msg.video_note
                file_type = "video_note"
        else:
            if getattr(msg, "voice", None):
                file_obj = msg.voice
                file_type = "voice"
            elif getattr(msg, "video_note", None):
                file_obj = msg.video_note
                file_type = "video_note"

    if file_obj is None or not file_type:
        if update.message:
            await update.message.reply_text(
                "Я могу обрабатывать только голосовые сообщения и видео-кружки."
            )
        return

    status_message = None
    if update.message:
        status_message = await update.message.reply_text(
            "Получил медиа! Скачиваю файл..."
        )

    file_path = None
    start_time = time.time()
    try:
        logger.info(f"Начало скачивания файла для пользователя {user_id}")
        unique_name = f"data/{uuid.uuid4().hex}_{file_type}.bin"
        telegram_file = await file_obj.get_file()
        await telegram_file.download_to_drive(unique_name)
        file_path = unique_name
        logger.info(f"Файл скачан: {file_path}")

        if status_message:
            await status_message.edit_text("Файл скачан. Запускаю транскрибацию...")

        huey_task = transcribe_task(file_path, file_type, language)
        try:
            transcribe_result = await aget_result(
                huey_task, backoff=1.15, max_delay=1.0, preserve=False
            )
        except Exception as e:
            logger.error(f"Ошибка ожидания результата huey: {e}")
            if status_message:
                await status_message.edit_text(
                    "Ошибка при обработке очереди. Попробуйте позже."
                )
            return
        duration = time.time() - start_time

        if not transcribe_result or not isinstance(transcribe_result, (list, tuple)):
            if update.message:
                await update.message.reply_text(
                    "Не удалось распознать текст. Возможно, аудио было слишком коротким или нечетким."
                )
            return

        raw_text, lang = transcribe_result if len(transcribe_result) == 2 else (transcribe_result[0], None)

        final_text = raw_text
        if raw_text:
            if status_message:
                await status_message.edit_text(
                    "Транскрибация завершена. Попытка исправить ошибки..."
                )
            corrected_text = await llm.correct_text_with_llm(raw_text)
            if corrected_text != raw_text:
                final_text = corrected_text
                if status_message:
                    await status_message.edit_text(
                        "Текст исправлен. Отправляю ответ..."
                    )
            else:
                if status_message:
                    await status_message.edit_text(
                        "Исправление текста не потребовалось или не удалось исправить. Отправляю ответ..."
                    )

        if final_text:
            if update.message:
                is_admin = False
                user = update.effective_user
                user_id = user.id if user else None
                if ADMIN_ID is not None and user_id == ADMIN_ID:
                    is_admin = True
                await update.message.reply_text(
                    f"`{final_text}`",
                    parse_mode="Markdown",
                    reply_markup=get_admin_keyboard() if is_admin else get_user_keyboard(),
                )
            if user_id is not None:
                database.record_task_metadata(
                    DB_PATH, user_id, duration, file_type, final_text
                )
        else:
            if update.message:
                is_admin = False
                user = update.effective_user
                user_id = user.id if user else None
                if ADMIN_ID is not None and user_id == ADMIN_ID:
                    is_admin = True
                await update.message.reply_text(
                    "Не удалось распознать текст. Возможно, аудио было слишком коротким или нечетким.",
                    reply_markup=get_admin_keyboard() if is_admin else get_user_keyboard(),
                )

    except asyncio.CancelledError:
        logger.info(f"Задача для пользователя {user_id} была отменена.")
        if status_message:
            await status_message.edit_text("Обработка отменена.")
    except Exception:
        logger.exception(f"Ошибка при обработке медиа для пользователя {user_id}:")
        if status_message:
            await status_message.edit_text(
                "Произошла внутренняя ошибка при обработке. Пожалуйста, попробуй еще раз позже."
            )
    finally:
        pass


async def handle_admin_id_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Обработчик ввода ID пользователя для добавления или удаления."""
    user = update.effective_user
    user_id = user.id if user else None
    if ADMIN_ID is None or user_id != ADMIN_ID:
        return
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    user_data = getattr(context, "user_data", {}) or {}
    action = user_data.get("admin_action")
    if text.isdigit() and action:
        try:
            target_id = int(text)
            if action == "add":
                try:
                    chat = await context.bot.get_chat(target_id)
                    first_name = chat.first_name or ""
                    last_name = chat.last_name or ""
                    username = chat.username or ""
                except Exception:
                    first_name = ""
                    last_name = ""
                    username = ""
                database.add_user(DB_PATH, target_id, first_name=first_name, last_name=last_name, username=username)
                await update.message.reply_text(
                    f"Пользователь с ID `{target_id}` успешно добавлен в список разрешённых!",
                    parse_mode="Markdown",
                    reply_markup=get_admin_keyboard(),
                )
                try:
                    await context.bot.send_message(
                        chat_id=target_id,
                        text="Поздравляю! Тебе предоставлен доступ к боту для транскрибации голосовых сообщений. Начни с /start!",
                    )
                except Exception as e:
                    logger.warning(
                        f"Не удалось отправить сообщение новому пользователю {target_id}: {e}"
                    )
                    await update.message.reply_text(
                        f"Пользователь добавлен, но не удалось ему отправить сообщение {target_id}, возможно, он не начал диалог с ботом."
                    )
            elif action == "remove":
                database.remove_user(DB_PATH, target_id)
                await update.message.reply_text(
                    f"Пользователь с ID `{target_id}` успешно удалён из списка разрешённых.",
                    parse_mode="Markdown",
                    reply_markup=get_admin_keyboard(),
                )
            if hasattr(context, "user_data") and context.user_data is not None:
                context.user_data["admin_action"] = None
        except Exception:
            await update.message.reply_text(
                "Ошибка при обработке ID пользователя. Проверьте ID и попробуйте ещё раз.",
                reply_markup=get_admin_keyboard(),
            )
            if hasattr(context, "user_data") and context.user_data is not None:
                context.user_data["admin_action"] = None


def main() -> None:
    """Запуск бота."""
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN не установлен!")
        return

    admin_id_int = int(ADMIN_ID) if ADMIN_ID is not None else None
    if admin_id_int is not None and not database.is_user_allowed(DB_PATH, admin_id_int):
        logger.info(f"Добавление администратора {admin_id_int} в базу при первом запуске.")
        database.add_user(DB_PATH, admin_id_int, is_admin=True)

    application = Application.builder().token(TOKEN).concurrent_updates(True).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("admin_menu", admin_menu_command))
    application.add_handler(CommandHandler("add_user", add_user_command))
    application.add_handler(CommandHandler("remove_user", remove_user_command))
    application.add_handler(CommandHandler("list_users", list_users_command))

    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex("Добавить пользователя"), add_user_command
        )
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex("Удалить пользователя"), remove_user_command
        )
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex("Список пользователей"), list_users_command
        )
    )
    application.add_handler(
        MessageHandler(filters.TEXT & filters.Regex(r"^\d+$"), handle_admin_id_input)
    )

    application.add_handler(
        MessageHandler(filters.VOICE | filters.VIDEO_NOTE, handle_media)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex("Язык"), handle_language_menu
        )
    )
    application.add_handler(
        MessageHandler(filters.TEXT & filters.Regex("^(Русский|Английский)"), handle_language_choice)
    )

    logger.info("Бот запущен! 🤖")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
