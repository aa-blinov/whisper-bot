"""Экранирование и нарезка текста для Telegram."""

from __future__ import annotations

import html

MAX_MESSAGE_CHARS = 3_800


def escape(text: object) -> str:
    """Экранировать значение для HTML-разметки Telegram."""
    return html.escape(str(text or ""))


def split_text(text: str, limit: int = MAX_MESSAGE_CHARS) -> list[str]:
    """Разбить длинный текст по строкам, чтобы влезть в лимит Telegram."""
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
    """Куски расшифровки, каждый уже в HTML-разметке."""
    return [f"<blockquote>{escape(chunk)}</blockquote>" for chunk in split_text(text)]
