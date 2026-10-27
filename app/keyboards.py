"""Клавиатуры бота: ответные и inline.

Текст кнопок и обработчики живут в одном месте: кнопку ищу по той же
константе, что и рисую, поэтому переименование не ломает нажатие.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

BTN_LANGUAGE = "🌐 Язык"
BTN_USERS = "👥 Пользователи"
BTN_STATS = "📊 Статистика"
BTN_ADMIN = "⚙️ Админ-панель"
BTN_ADD = "➕ Добавить пользователя"
BTN_INVITE = "🔗 Приглашение"
BTN_HELP = "❓ Помощь"
BTN_CANCEL = "✖️ Отмена"

BTN_RU = "🇷🇺 Русский"
BTN_EN = "🇬🇧 Английский"

LANGUAGE_NAMES = {"ru": "русский", "en": "английский"}


def user_menu() -> ReplyKeyboardMarkup:
    """Меню обычного пользователя."""
    return ReplyKeyboardMarkup(
        [[KeyboardButton(BTN_LANGUAGE)]],
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=True,
    )


def admin_menu() -> ReplyKeyboardMarkup:
    """Меню администратора."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_USERS), KeyboardButton(BTN_STATS)],
            [KeyboardButton(BTN_ADD), KeyboardButton(BTN_INVITE)],
            [KeyboardButton(BTN_LANGUAGE), KeyboardButton(BTN_ADMIN)],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=True,
    )


def main_menu(is_admin: bool) -> ReplyKeyboardMarkup:
    return admin_menu() if is_admin else user_menu()


def language_menu(current: str) -> ReplyKeyboardMarkup:
    """Выбор языка; текущий помечен, чтобы не гадать, какой стоит."""
    ru = f"{BTN_RU} · выбран" if current == "ru" else BTN_RU
    en = f"{BTN_EN} · выбран" if current == "en" else BTN_EN
    return ReplyKeyboardMarkup(
        [[KeyboardButton(ru), KeyboardButton(en)], [KeyboardButton(BTN_CANCEL)]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def cancel_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(BTN_CANCEL)]], resize_keyboard=True, one_time_keyboard=False
    )


def admin_home(count: int) -> InlineKeyboardMarkup:
    """Панель администратора: всё, что делается с людьми, в два нажатия."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"👥 Пользователи ({count})", callback_data="admin:list")],
            [InlineKeyboardButton("➕ Добавить", callback_data="admin:add")],
            [InlineKeyboardButton("🔗 Ссылка-приглашение", callback_data="admin:invite")],
            [InlineKeyboardButton("📊 Статистика", callback_data="admin:stats")],
        ]
    )


def users_list(users: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for user in users:
        mark = "👑 " if user.get("is_admin") else "👤 "
        rows.append(
            [
                InlineKeyboardButton(
                    f"{mark}{display_name(user)} · {user['user_id']}",
                    callback_data=f"user:{user['user_id']}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin:home")])
    return InlineKeyboardMarkup(rows)


def user_card(user: dict) -> InlineKeyboardMarkup:
    user_id = user["user_id"]
    rows = [[InlineKeyboardButton("🗑 Удалить доступ", callback_data=f"user:{user_id}:del")]]
    rows.append([InlineKeyboardButton("⬅️ К списку", callback_data="admin:list")])
    return InlineKeyboardMarkup(rows)


def confirm_remove(user: dict) -> InlineKeyboardMarkup:
    user_id = user["user_id"]
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Да, удалить", callback_data=f"user:{user_id}:del:yes"),
                InlineKeyboardButton("⬅️ Оставить", callback_data=f"user:{user_id}"),
            ]
        ]
    )


def confirm_add(user_id: int, name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"✅ Добавить {name}", callback_data=f"add:{user_id}")],
            [InlineKeyboardButton("✖️ Отмена", callback_data="admin:home")],
        ]
    )


def access_request(user_id: int, name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Разрешить", callback_data=f"req:{user_id}:allow"),
                InlineKeyboardButton("🚫 Отклонить", callback_data=f"req:{user_id}:deny"),
            ]
        ]
    )


def back_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin:home")]])


def display_name(user: dict) -> str:
    """Имя человека для списков и карточек."""
    if not user:
        return "без имени"
    full = " ".join(
        part for part in (user.get("first_name") or "", user.get("last_name") or "") if part
    ).strip()
    username = user.get("username")
    if full and username:
        return f"{full} (@{username})"
    if full:
        return full
    if username:
        return f"@{username}"
    return str(user.get("user_id", ""))
