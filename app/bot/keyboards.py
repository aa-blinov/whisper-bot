"""Клавиатуры бота: ответные и inline.

Текст кнопок и обработчики живут в одном месте: кнопку ищу по той же
константе, что и рисую, поэтому переименование не ломает нажатие.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app.domain import User

BTN_LANGUAGE = "🌐 Язык"
BTN_USERS = "👥 Люди"
BTN_STATS = "📊 Статистика"
BTN_ADMIN = "⚙️ Админ-панель"
BTN_ADD = "➕ Добавить человека"
BTN_INVITE = "🔗 Приглашение"
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
            [InlineKeyboardButton(f"👥 Люди ({count})", callback_data="admin:list")],
            [InlineKeyboardButton("➕ Добавить", callback_data="admin:add")],
            [InlineKeyboardButton("🔗 Ссылка для приглашения", callback_data="admin:invite")],
            [InlineKeyboardButton("📊 Статистика", callback_data="admin:stats")],
        ]
    )


def users_list(users: list[User]) -> InlineKeyboardMarkup:
    rows = []
    for user in users:
        mark = "👑 " if user.is_admin else "👤 "
        rows.append(
            [
                InlineKeyboardButton(
                    f"{mark}{user.display_name} · {user.user_id}",
                    callback_data=f"user:{user.user_id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin:home")])
    return InlineKeyboardMarkup(rows)


def user_card(user: User) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                "🗑 Закрыть доступ", callback_data=f"user:{user.user_id}:del"
            )
        ],
        [InlineKeyboardButton("⬅️ К списку", callback_data="admin:list")],
    ]
    return InlineKeyboardMarkup(rows)


def confirm_remove(user: User) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Да, закрыть", callback_data=f"user:{user.user_id}:del:yes"
                ),
                InlineKeyboardButton("⬅️ Оставить", callback_data=f"user:{user.user_id}"),
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


def access_request(user_id: int) -> InlineKeyboardMarkup:
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
