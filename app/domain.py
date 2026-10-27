"""Типы предметной области, общие для всех слоёв.

Здесь нет ни Telegram, ни SQLite, ни ONNX: только то, чем обмениваются
сервисы и обработчики.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    """Человек из списка допущенных."""

    user_id: int
    is_admin: bool = False
    first_name: str = ""
    last_name: str = ""
    username: str = ""
    language: str = "ru"
    created_at: str | None = None

    @property
    def full_name(self) -> str:
        return " ".join(part for part in (self.first_name, self.last_name) if part).strip()

    @property
    def display_name(self) -> str:
        """Имя для списков и карточек, с username, если он есть."""
        full = self.full_name
        if full and self.username:
            return f"{full} (@{self.username})"
        if full:
            return full
        if self.username:
            return f"@{self.username}"
        return str(self.user_id)


@dataclass(frozen=True)
class Stats:
    """Счётчики для `/stats`."""

    total_users: int = 0
    today_active: int = 0
    today_requests: int = 0
    today_new: int = 0
    week_active: int = 0
    week_requests: int = 0
    week_new: int = 0


@dataclass(frozen=True)
class Transcript:
    """Результат распознавания."""

    text: str
    language: str = "ru"
