"""Администрирование доступа: панель, добавление, удаление, статистика.

Добавить человека можно тремя способами, и все три ведут к одной карточке
с кнопкой подтверждения: номер, `@username` или пересланное сообщение, из
которого берутся номер и имя. Человек, который впервые написал боту,
присылает заявку: админу приходит карточка с кнопками «Разрешить» и
«Отклонить».
"""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime

from telegram import InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import database
import keyboards
from config import settings

logger = logging.getLogger(__name__)

WAITING_USER = 1

USERNAME_RE = re.compile(r"^(?:@|https?://t\.me/)([A-Za-z0-9_]{4,32})/?$")


def db_path(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.bot_data["settings"].db_path


def is_admin(user_id: int | None) -> bool:
    """Админом считается тот, кто указан в `ADMIN_ID` или помечен в базе."""
    if user_id is None:
        return False
    if user_id in settings.admin_ids:
        return True
    return bool((database.get_user(settings.db_path, user_id) or {}).get("is_admin"))


def admin_ids(context: ContextTypes.DEFAULT_TYPE) -> list[int]:
    """Все админы: из окружения и из базы, без повторов."""
    found = list(dict.fromkeys(settings.admin_ids))
    for user in database.get_all_users(db_path(context)):
        if user.get("is_admin") and user["user_id"] not in found:
            found.append(user["user_id"])
    return found


async def notify_admins(
    context: ContextTypes.DEFAULT_TYPE, text: str, markup: InlineKeyboardMarkup | None = None
) -> None:
    for admin_id in admin_ids(context):
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
                disable_web_page_preview=True,
            )
        except Exception as exc:
            logger.warning("Не удалось написать админу %s: %s", admin_id, exc)


async def _answer(query, text: str | None = None, alert: bool = False) -> None:
    """Ответить на нажатие, не падая на повторном или устаревшем запросе."""
    try:
        await query.answer(text or None, show_alert=alert)
    except Exception as exc:
        logger.debug("callback уже отвечен: %s", exc)


async def _say_not_admin(update: Update) -> None:
    if update.callback_query:
        await _answer(update.callback_query, "Это только для администратора", alert=True)
        return
    if update.effective_message:
        await update.effective_message.reply_text("Команда доступна только администратору.")


def _deny(update: Update) -> bool:
    """True, если это не админ и обработчик должен остановиться."""
    user = update.effective_user
    return not is_admin(user.id if user else None)


def _menu_for(user_id: int | None) -> keyboards.ReplyKeyboardMarkup:
    return keyboards.main_menu(is_admin(user_id))


def _panel_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    total = database.count_users(db_path(context))
    return (
        "⚙️ <b>Админ-панель</b>\n\n"
        f"Допущено людей: <b>{total}</b>\n"
        "Выбери действие кнопкой ниже или отправь /add_user."
    )


async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _deny(update):
        await _say_not_admin(update)
        return

    user = update.effective_user
    user_id = user.id if user else None
    total = database.count_users(db_path(context))

    if update.callback_query:
        await _answer(update.callback_query)
        await update.callback_query.edit_message_text(
            _panel_text(context),
            parse_mode=ParseMode.HTML,
            reply_markup=keyboards.admin_home(total),
        )
        return

    message = update.effective_message
    if message is None:
        return
    # Ответную клавиатуру показываем один раз за сессию, дальше всё
    # делается inline-кнопками, чтобы не дублировать меню.
    if not context.user_data.get("admin_menu_sent"):
        await message.reply_text("Меню админа внизу.", reply_markup=_menu_for(user_id))
        context.user_data["admin_menu_sent"] = True
    await message.reply_text(
        _panel_text(context),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.admin_home(total),
    )


def _users_text(users: list[dict]) -> str:
    lines = [f"👥 <b>Допущенные люди</b>, {len(users)}"]
    for user in users:
        crown = "👑" if user.get("is_admin") else "•"
        name = html.escape(keyboards.display_name(user))
        lines.append(f"{crown} {name}, <code>{user['user_id']}</code>")
    lines.append("")
    lines.append("Нажми на имя, чтобы открыть карточку.")
    return "\n".join(lines)


async def show_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _deny(update):
        await _say_not_admin(update)
        return
    users = database.get_all_users(db_path(context))
    text = _users_text(users) if users else "Пока никого нет. Добавь первого кнопкой «➕ Добавить»."
    markup = keyboards.users_list(users) if users else keyboards.back_home()

    if update.callback_query:
        await _answer(update.callback_query)
        await update.callback_query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup
        )
    elif update.effective_message:
        await update.effective_message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup
        )


async def user_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    if _deny(update):
        await _answer(query, "Это только для администратора", alert=True)
        return

    user_id = int(query.data.split(":")[1])
    user = database.get_user(db_path(context), user_id)
    if not user:
        await _answer(query, "Такого человека уже нет в списке", alert=True)
        await show_users(update, context)
        return

    await _answer(query)
    added = (user.get("created_at") or "")[:10]
    lines = [
        f"👤 <b>{html.escape(keyboards.display_name(user))}</b>",
        f"ID: <code>{user_id}</code>",
        f"Язык: {html.escape(keyboards.LANGUAGE_NAMES.get(user.get('language') or 'ru', 'русский'))}",
    ]
    if user.get("is_admin"):
        lines.append("Статус: 👑 администратор")
    if added:
        lines.append(f"Добавлен: {added}")
    await query.edit_message_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.user_card(user),
    )


async def user_confirm_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    if _deny(update):
        await _answer(query, "Это только для администратора", alert=True)
        return

    user_id = int(query.data.split(":")[1])
    user = database.get_user(db_path(context), user_id)
    if not user:
        await _answer(query, "Такого человека уже нет", alert=True)
        return
    if user_id in settings.admin_ids:
        await _answer(query, "Этого админа задаёт .env, здесь его не убрать", alert=True)
        return

    await _answer(query)
    await query.edit_message_text(
        f"Закрыть доступ для <b>{html.escape(keyboards.display_name(user))}</b>?",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.confirm_remove(user),
    )


async def user_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    if _deny(update):
        await _answer(query, "Это только для администратора", alert=True)
        return

    user_id = int(query.data.split(":")[1])
    user = database.get_user(db_path(context), user_id) or {"user_id": user_id}
    removed = database.remove_user(db_path(context), user_id)
    await _answer(query, "Доступ закрыт" if removed else "Такого человека нет")

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="Администратор закрыл доступ к боту. Если это ошибка, напиши ему.",
        )
    except Exception as exc:
        logger.info("Не удалось уведомить %s о закрытии доступа: %s", user_id, exc)

    users = database.get_all_users(db_path(context))
    await query.edit_message_text(
        _users_text(users) if users else "Пока никого нет. Добавь первого кнопкой «➕ Добавить».",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.users_list(users) if users else keyboards.back_home(),
    )
    logger.info("Админ закрыл доступ %s (%s)", user_id, keyboards.display_name(user))


async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало добавления: просим номер, @username или пересланное сообщение."""
    if _deny(update):
        await _say_not_admin(update)
        return ConversationHandler.END

    context.user_data["admin_action"] = "add"
    text = (
        "➕ <b>Кого добавить?</b>\n\n"
        "Пришли одно из трёх:\n"
        "• номер, например <code>123456789</code>\n"
        "• имя пользователя, например <code>@someone</code>\n"
        "• пересланное сообщение этого человека\n\n"
        "Передумал? /cancel"
    )
    if update.callback_query:
        await _answer(update.callback_query)
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML)
    elif update.effective_message:
        await update.effective_message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=keyboards.cancel_menu()
        )
    return WAITING_USER


async def _resolve_username(context: ContextTypes.DEFAULT_TYPE, username: str) -> dict | None:
    try:
        chat = await context.bot.get_chat(f"@{username}")
    except Exception as exc:
        logger.info("Не удалось найти @%s: %s", username, exc)
        return None
    return {
        "user_id": chat.id,
        "first_name": chat.first_name or "",
        "last_name": chat.last_name or "",
        "username": chat.username or username,
    }


def _from_forward(message) -> dict | None:
    """Профиль человека из пересланного сообщения."""
    origin = getattr(message, "forward_origin", None)
    sender = getattr(origin, "sender_user", None) if origin else None
    if sender is None:
        return None
    return {
        "user_id": sender.id,
        "first_name": sender.first_name or "",
        "last_name": sender.last_name or "",
        "username": sender.username or "",
    }


async def add_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Разобрать ответ админа и показать карточку подтверждения."""
    message = update.effective_message
    if not message:
        return WAITING_USER
    if _deny(update):
        await _say_not_admin(update)
        return ConversationHandler.END

    text = (message.text or "").strip()
    if text in (keyboards.BTN_CANCEL, "/cancel"):
        await message.reply_text(
            "Никого не добавил.", reply_markup=_menu_for(update.effective_user.id)
        )
        return ConversationHandler.END

    candidate = _from_forward(message)
    if candidate is None and text.isdigit():
        user_id = int(text)
        try:
            chat = await context.bot.get_chat(user_id)
            candidate = {
                "user_id": chat.id,
                "first_name": chat.first_name or "",
                "last_name": chat.last_name or "",
                "username": chat.username or "",
            }
        except Exception:
            candidate = {"user_id": user_id, "first_name": "", "last_name": "", "username": ""}
    if candidate is None:
        match = USERNAME_RE.match(text)
        if match:
            candidate = await _resolve_username(context, match.group(1))

    if candidate is None:
        await message.reply_text(
            "Не понял, кого добавить. Нужен номер, @username или пересланное сообщение.",
            reply_markup=keyboards.cancel_menu(),
        )
        return WAITING_USER

    user_id = candidate["user_id"]
    existing = database.get_user(db_path(context), user_id)
    if existing:
        await message.reply_text(
            f"Этот человек уже в списке: <b>{html.escape(keyboards.display_name(existing))}</b>.",
            parse_mode=ParseMode.HTML,
            reply_markup=_menu_for(update.effective_user.id),
        )
        return ConversationHandler.END

    name = keyboards.display_name(candidate)
    await message.reply_text(
        "Добавить этого человека?\n\n"
        f"👤 <b>{html.escape(name)}</b>\n"
        f"ID: <code>{user_id}</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.confirm_add(user_id, html.escape(name)),
    )
    context.user_data["pending_user"] = candidate
    return ConversationHandler.END


async def add_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Подтверждение добавления по inline-кнопке."""
    query = update.callback_query
    if not query:
        return
    if _deny(update):
        await _answer(query, "Это только для администратора", alert=True)
        return

    user_id = int(query.data.split(":")[1])
    pending = context.user_data.pop("pending_user", None) or {}
    if pending.get("user_id") != user_id:
        pending = database.get_user(db_path(context), user_id) or {}

    database.add_user(
        db_path(context),
        user_id,
        first_name=pending.get("first_name", ""),
        last_name=pending.get("last_name", ""),
        username=pending.get("username", ""),
    )
    user = database.get_user(db_path(context), user_id) or {"user_id": user_id}
    name = keyboards.display_name(user)

    await _answer(query, "Доступ выдан")
    await query.edit_message_text(
        f"✅ Доступ выдан: <b>{html.escape(name)}</b> (<code>{user_id}</code>).",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.back_home(),
    )
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "🎉 Тебе открыли доступ.\n\n"
                "Пришли голосовое сообщение или видео-кружок, я верну текст с пунктуацией."
            ),
            reply_markup=keyboards.user_menu(),
        )
    except Exception as exc:
        logger.info("Пользователь %s не получил приветствие: %s", user_id, exc)
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text=(
                "Доступ выдан, но написать человеку не вышло: он ещё не начинал "
                "диалог с ботом. Попроси его нажать /start."
            ),
        )
    logger.info("Админ выдал доступ %s (%s)", user_id, name)


async def invite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ссылка на бота, которую админ пересылает сам."""
    if _deny(update):
        await _say_not_admin(update)
        return
    username = context.bot.username
    link = f"https://t.me/{username}" if username else "ссылку получить не вышло"
    text = (
        "🔗 <b>Ссылка для приглашения</b>\n\n"
        f"<code>{html.escape(link)}</code>\n\n"
        "Перешли её человеку. Когда он нажмёт /start, тебе придёт заявка с "
        "кнопками «Разрешить» и «Отклонить»."
    )
    if update.callback_query:
        await _answer(update.callback_query)
        await update.callback_query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=keyboards.back_home()
        )
    elif update.effective_message:
        await update.effective_message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=keyboards.back_home()
        )


def _stats_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    stats = database.get_bot_stats(db_path(context))
    options = context.bot_data["settings"]
    today = datetime.now().strftime("%d.%m.%Y")
    return (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Людей: <b>{stats['total_users']}</b>\n\n"
        f"Сегодня, {today}:\n"
        f"• активных: {stats['today_active']}\n"
        f"• запросов: {stats['today_requests']}\n"
        f"• новых: {stats['today_new']}\n\n"
        "За 7 дней:\n"
        f"• активных: {stats['week_active']}\n"
        f"• запросов: {stats['week_requests']}\n"
        f"• новых: {stats['week_new']}\n\n"
        f"🧠 Модель: {html.escape(options.asr_model)} "
        f"({html.escape(options.asr_quantization or 'fp32')}, ONNX)"
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _deny(update):
        await _say_not_admin(update)
        return
    text = _stats_text(context)
    if update.callback_query:
        await _answer(update.callback_query)
        await update.callback_query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=keyboards.back_home()
        )
    elif update.effective_message:
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def access_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Заявка на доступ. True, если заявка ушла администратору."""
    user = update.effective_user
    if user is None:
        return False
    db = db_path(context)

    # Пока админа нет ни в .env, ни в базе, первый написавший становится им:
    # иначе ботом нельзя пользоваться вообще, а токен знает только владелец.
    if not settings.admin_ids and not database.has_admins(db):
        database.add_user(
            db,
            user.id,
            is_admin=True,
            first_name=user.first_name or "",
            last_name=user.last_name or "",
            username=user.username or "",
        )
        logger.warning("ADMIN_ID не задан: администратором стал первый написавший, %s", user.id)
        return False

    name = html.escape(user.full_name or str(user.id))
    username = f" (@{html.escape(user.username)})" if user.username else ""
    await notify_admins(
        context,
        f"🔔 <b>Заявка на доступ</b>\n\n{name}{username}\nID: <code>{user.id}</code>",
        keyboards.access_request(user.id, (user.full_name or "")[:32]),
    )
    return True


async def access_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Разрешить или отклонить заявку одной кнопкой."""
    query = update.callback_query
    if not query:
        return
    if _deny(update):
        await _answer(query, "Это только для администратора", alert=True)
        return

    _, raw_id, action = query.data.split(":")
    user_id = int(raw_id)
    if action == "allow":
        try:
            chat = await context.bot.get_chat(user_id)
            first_name = chat.first_name or ""
            last_name = chat.last_name or ""
            username = chat.username or ""
        except Exception:
            first_name = last_name = username = ""
        database.add_user(
            db_path(context),
            user_id,
            first_name=first_name,
            last_name=last_name,
            username=username,
        )
        await _answer(query, "Доступ выдан")
        await query.edit_message_text(
            f"✅ Доступ выдан: <code>{user_id}</code>", parse_mode=ParseMode.HTML
        )
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "🎉 Доступ открыт!\n\n"
                    "Пришли голосовое сообщение или видео-кружок, я верну текст с пунктуацией."
                ),
                reply_markup=keyboards.user_menu(),
            )
        except Exception as exc:
            logger.info("Не удалось написать %s: %s", user_id, exc)
    else:
        await _answer(query, "Отклонено")
        await query.edit_message_text(
            f"🚫 Заявке <code>{user_id}</code> отказано.", parse_mode=ParseMode.HTML
        )
        try:
            await context.bot.send_message(
                chat_id=user_id, text="К сожалению, доступ к боту не открыли."
            )
        except Exception:
            pass


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_message:
        await update.effective_message.reply_text(
            "Отменено.",
            reply_markup=_menu_for(update.effective_user.id if update.effective_user else None),
        )
    return ConversationHandler.END


def build_handlers() -> list:
    """Обработчики админской части, в порядке регистрации."""
    add_conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(add_start, pattern=r"^admin:add$"),
            CommandHandler("add_user", add_start),
            MessageHandler(filters.Regex(rf"^{re.escape(keyboards.BTN_ADD)}$"), add_start),
        ],
        states={
            WAITING_USER: [
                MessageHandler(filters.ALL & ~filters.COMMAND, add_receive),
                CommandHandler("cancel", cmd_cancel),
            ]
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
    )

    return [
        add_conversation,
        CommandHandler(["admin", "admin_menu", "panel"], panel),
        CommandHandler("list_users", show_users),
        CommandHandler("users", show_users),
        CommandHandler("remove_user", show_users),
        CommandHandler("invite", invite),
        CommandHandler("stats", stats),
        CallbackQueryHandler(panel, pattern=r"^admin:home$"),
        CallbackQueryHandler(show_users, pattern=r"^admin:list$"),
        CallbackQueryHandler(stats, pattern=r"^admin:stats$"),
        CallbackQueryHandler(invite, pattern=r"^admin:invite$"),
        CallbackQueryHandler(add_confirm, pattern=r"^add:\d+$"),
        CallbackQueryHandler(access_decision, pattern=r"^req:\d+:(allow|deny)$"),
        CallbackQueryHandler(user_remove, pattern=r"^user:\d+:del:yes$"),
        CallbackQueryHandler(user_confirm_remove, pattern=r"^user:\d+:del$"),
        CallbackQueryHandler(user_card, pattern=r"^user:\d+$"),
        MessageHandler(filters.Regex(rf"^{re.escape(keyboards.BTN_ADMIN)}$"), panel),
        MessageHandler(filters.Regex(rf"^{re.escape(keyboards.BTN_USERS)}$"), show_users),
        MessageHandler(filters.Regex(rf"^{re.escape(keyboards.BTN_STATS)}$"), stats),
        MessageHandler(filters.Regex(rf"^{re.escape(keyboards.BTN_INVITE)}$"), invite),
    ]
