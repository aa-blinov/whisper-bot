"""Всё, что бот говорит человеку.

Тексты собраны в одном файле, чтобы формулировки не расползались по
обработчикам и чтобы их можно было вычитать целиком. Динамические части
экранируются здесь же.
"""

from __future__ import annotations

from app.domain import Stats, User
from app.bot.formatting import escape

START = (
    "Привет, {name}!\n\n"
    "Пришли голосовое, видео-кружок, аудиофайл или видео, и я верну текст. "
    "Речь распознаётся вместе с пунктуацией, модель работает на этом же сервере."
)
ADMIN_HINT = "\n\nТы администратор. Команда /admin открывает доступы, список людей и статистику."

NOT_ADMIN = "Команда доступна только администратору."
CALLBACK_NOT_ADMIN = "Это только для администратора"


def start(name: str, is_admin: bool) -> str:
    text = START.format(name=escape(name))
    return text + ADMIN_HINT if is_admin else text


def help_text(is_admin: bool) -> str:
    lines = [
        "<b>Что умеет бот</b>",
        "• голосовое сообщение становится текстом",
        "• видео-кружок тоже",
        "• аудиофайл (mp3, ogg, wav, flac, m4a) и видеофайл тоже",
        "• в тексте есть пунктуация и заглавные буквы",
        "",
        "<b>Команды</b>",
        "/language: русский или английский",
        "/help: эта справка",
    ]
    if is_admin:
        lines += [
            "",
            "<b>Администратору</b>",
            "/admin: доступы, список людей и статистика",
            "/add_user: добавить человека",
            "/users: список допущенных",
            "/invite: ссылка для приглашения",
            "/stats: статистика",
        ]
    return "\n".join(lines)


LANGUAGE_MENU = "Выбери язык распознавания:"
LANGUAGE_EN_NOTE = (
    "\n\nАнглийскую речь распознаёт вторая модель, поэтому первый такой запрос идёт дольше."
)


def language_set(language_name: str, note: str = "") -> str:
    return f"Язык распознавания: {language_name}.{note}"


CANCELLED = "Хорошо, вернулся в меню."
ADD_CANCELLED = "Никого не добавил."
MENU_READY = "Меню админа внизу."
FALLBACK = (
    "Пришли голосовое сообщение или видео-кружок, я превращу его в текст.\n"
    "Все команды: /help"
)
ERROR = "Что-то пошло не так. Попробуй ещё раз или напиши позже."

DOWNLOADS = "🎧 Получил запись…"
RECOGNIZING = "🧠 Распознаю…"
INTERNAL_ERROR = "Что-то сломалось при обработке. Попробуй ещё раз."
TIMEOUT = "Распознавание затянулось. Попробуй ещё раз чуть позже."
NOT_RECOGNIZED = "Не расслышал текст. Запись слишком короткая или тихая?"
UNSUPPORTED = (
    "Это не похоже на аудио или видео. Пришли голосовое, кружок, "
    "аудиофайл или видео."
)


def file_too_big(limit_mb: int, size_mb: float = 0) -> str:
    """Отказ с готовой командой: сжать или порезать совещание."""
    head = (
        f"Файл {size_mb:.0f} МБ, а лимит {limit_mb} МБ."
        if size_mb
        else f"Файл больше {limit_mb} МБ."
    )
    return (
        f"{head} Телеграм отдаёт ботам не больше {limit_mb} МБ.\n\n"
        "<b>Сожми звук</b>, речь останется разборчивой:\n"
        '<pre>ffmpeg -i "совещание.mp3" -ac 1 -ar 16000 -b:a 32k '
        '"совещание-small.mp3"</pre>\n'
        "Часовое совещание так весит около 15 МБ.\n\n"
        "<b>Если всё равно много, порежь по 30 минут:</b>\n"
        '<pre>ffmpeg -ss 0 -t 1800 -i "совещание.mp3" -ac 1 -ar 16000 '
        '-b:a 32k "часть1.mp3"</pre>\n'
        "Второй кусок: замени <code>-ss 0</code> на <code>-ss 1800</code>.\n\n"
        "Лимит можно поднять до 2 ГБ локальным сервером Bot API: "
        "https://github.com/aa-blinov/lazy-to-text-bot"
        "#large-files-and-long-meetings"
    )


def media_too_long(duration: int, maximum: int) -> str:
    minutes = maximum // 60
    return (
        f"Запись длится {duration} с, а максимум {maximum} с "
        f"(около {minutes} минут).\n\n"
        "Порежь её на куски и пришли по очереди:\n"
        '<pre>ffmpeg -ss 0 -t 1800 -i "запись.mp3" -ac 1 -ar 16000 '
        '-b:a 32k "часть1.mp3"</pre>'
    )


def access_denied_pending() -> str:
    return (
        "Пока нет доступа. Я отправил заявку администратору, и как только он её "
        "подтвердит, можно присылать голосовые."
    )


ACCESS_DENIED = "Пока нет доступа. Напиши администратору."
ACCESS_REVOKED = "Администратор закрыл доступ к боту. Если это ошибка, напиши ему."
ACCESS_REFUSED = "К сожалению, доступ к боту не открыли."
WELCOME_NEW = (
    "🎉 Тебе открыли доступ.\n\n"
    "Пришли голосовое сообщение или видео-кружок, я верну текст с пунктуацией."
)
WELCOME_FAILED = (
    "Доступ выдан, но написать человеку не вышло: он ещё не начинал диалог с ботом. "
    "Попроси его нажать /start."
)


def panel(count: int) -> str:
    return (
        "⚙️ <b>Админ-панель</b>\n\n"
        f"Допущено людей: <b>{count}</b>\n"
        "Выбери действие кнопкой ниже или отправь /add_user."
    )


def users_list(users: list[User]) -> str:
    lines = [f"👥 <b>Допущенные люди</b>, {len(users)}"]
    for user in users:
        crown = "👑" if user.is_admin else "•"
        lines.append(f"{crown} {escape(user.display_name)}, <code>{user.user_id}</code>")
    lines += ["", "Нажми на имя, чтобы открыть карточку."]
    return "\n".join(lines)


USERS_EMPTY = "Пока никого нет. Добавь первого кнопкой «➕ Добавить»."


def user_card(user: User, language_name: str) -> str:
    lines = [
        f"👤 <b>{escape(user.display_name)}</b>",
        f"ID: <code>{user.user_id}</code>",
        f"Язык: {escape(language_name)}",
    ]
    if user.is_admin:
        lines.append("Статус: 👑 администратор")
    if user.created_at:
        lines.append(f"Добавлен: {user.created_at[:10]}")
    return "\n".join(lines)


def confirm_remove(name: str) -> str:
    return f"Закрыть доступ для <b>{escape(name)}</b>?"


ADD_PROMPT = (
    "➕ <b>Кого добавить?</b>\n\n"
    "Пришли одно из трёх:\n"
    "• номер, например <code>123456789</code>\n"
    "• имя пользователя, например <code>@someone</code>\n"
    "• пересланное сообщение этого человека\n\n"
    "Передумал? /cancel"
)
ADD_UNCLEAR = "Не понял, кого добавить. Нужен номер, @username или пересланное сообщение."


def add_already(name: str) -> str:
    return f"Этот человек уже в списке: <b>{escape(name)}</b>."


def add_confirm(name: str, user_id: int) -> str:
    return f"Добавить этого человека?\n\n👤 <b>{escape(name)}</b>\nID: <code>{user_id}</code>"


def added(name: str, user_id: int) -> str:
    return f"✅ Доступ выдан: <b>{escape(name)}</b> (<code>{user_id}</code>)."


def invite(link: str) -> str:
    return (
        "🔗 <b>Ссылка для приглашения</b>\n\n"
        f"<code>{escape(link)}</code>\n\n"
        "Перешли её человеку. Когда он нажмёт /start, тебе придёт заявка с "
        "кнопками «Разрешить» и «Отклонить»."
    )


def stats(stats_data: Stats, today: str, model: str, quantization: str) -> str:
    return (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Людей: <b>{stats_data.total_users}</b>\n\n"
        f"Сегодня, {today}:\n"
        f"• активных: {stats_data.today_active}\n"
        f"• запросов: {stats_data.today_requests}\n"
        f"• новых: {stats_data.today_new}\n\n"
        "За 7 дней:\n"
        f"• активных: {stats_data.week_active}\n"
        f"• запросов: {stats_data.week_requests}\n"
        f"• новых: {stats_data.week_new}\n\n"
        f"🧠 Модель: {escape(model)} ({escape(quantization)}, ONNX)"
    )


def access_request(user_id: int, full_name: str, username: str | None) -> str:
    handle = f" (@{escape(username)})" if username else ""
    return (
        "🔔 <b>Заявка на доступ</b>\n\n"
        f"{escape(full_name)}{handle}\nID: <code>{user_id}</code>"
    )


def access_granted(user_id: int) -> str:
    return f"✅ Доступ выдан: <code>{user_id}</code>"


def access_denied(user_id: int) -> str:
    return f"🚫 Заявке <code>{user_id}</code> отказано."


# Короткие ответы на нажатия (всплывающие подсказки кнопок).
ALERT_NO_USER_LIST = "Такого человека уже нет в списке"
ALERT_NO_USER = "Такого человека уже нет"
ALERT_ENV_ADMIN = "Этого админа задаёт .env, здесь его не убрать"
ALERT_GRANTED = "Доступ выдан"
ALERT_REVOKED = "Доступ закрыт"
ALERT_NOTHING_TO_REVOKE = "Такого человека нет"
ALERT_DENIED = "Отклонено"
