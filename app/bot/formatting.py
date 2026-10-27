"""Экранирование и нарезка текста для Telegram."""

from __future__ import annotations

import html

MAX_MESSAGE_CHARS = 3_800


def escape(text: object) -> str:
    """Экранировать значение для HTML-разметки Telegram."""
    return html.escape(str(text or ""))


def split_escaped(text: str, limit: int = MAX_MESSAGE_CHARS) -> list[str]:
    """Разбить уже экранированный текст, не разрывая HTML-сущность.

    Резать до экранирования нельзя: `&lt;` занимает четыре символа вместо
    одного, и кусок на 3800 исходных символов после экранирования
    переваливает за лимит Telegram в 4096.
    """
    chunks: list[str] = []
    rest = text
    while len(rest) > limit:
        cut = rest.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = rest.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        # Не режем посреди `&amp;`: отодвигаем границу до точки с запятой.
        amp = rest.rfind("&", 0, cut)
        semicolon = rest.rfind(";", 0, cut)
        if amp > semicolon:
            end = rest.find(";", amp)
            if end != -1 and end - cut < 8:
                cut = end + 1
        chunks.append(rest[:cut])
        rest = rest[cut:]
    if rest:
        chunks.append(rest)
    return chunks or [""]


def split_text(text: str, limit: int = MAX_MESSAGE_CHARS) -> list[str]:
    """Разбить исходный текст по строкам, чтобы влезть в лимит Telegram."""
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) > limit:
            chunks.append(current)
            current = line
        else:
            current += line
    if current:
        chunks.append(current)
    return chunks or [text]


def transcript_blocks(text: str) -> list[str]:
    """Куски расшифровки, каждый в HTML-разметке.

    Текст идёт блоком кода: у такого сообщения в клиентах Телеграма есть
    кнопка «копировать», а расшифровку почти всегда копируют. Сначала
    экранируем, потом режем: иначе после экранирования кусок вырастает и
    Телеграм отклоняет сообщение.
    """
    escaped = escape(text)
    return [f"<pre>{chunk}</pre>" for chunk in split_escaped(escaped)]
