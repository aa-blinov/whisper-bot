"""Необязательная правка расшифровки языковой моделью через OpenRouter.

GigaAM уже отдаёт текст с пунктуацией, поэтому этот шаг — только про
опечатки распознавания. Без `OPENROUTER_API_KEY` он выключен, и текст
уходит пользователю как есть.
"""

from __future__ import annotations

import json
import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT_SECONDS = 20.0

LLM_PROMPT_TEMPLATE = (
    "Текст ниже получен автоматическим распознаванием русской речи. "
    "Он уже с пунктуацией и заглавными буквами — её менять не нужно. "
    "Исправь только явные ошибки распознавания: ослышанные слова, "
    "разорванные слова, неверные имена и числа. "
    "Не перефразируй, не меняй стиль, не добавляй и не убирай смысл. "
    "Верни только исправленный текст, без пояснений:\n\n{text}"
)


async def correct_text(text: str) -> str | None:
    """Вернуть исправленный текст или None, если правка недоступна."""
    if not settings.llm_enabled:
        return None

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "X-Title": "whisper-bot",
    }
    payload = {
        "model": settings.openrouter_model,
        "messages": [
            {"role": "system", "content": "/no_think"},
            {"role": "user", "content": LLM_PROMPT_TEMPLATE.format(text=text)},
        ],
        "temperature": 0.1,
        "max_tokens": 2048,
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.post(OPENROUTER_API_URL, headers=headers, json=payload)
            response.raise_for_status()
            corrected = response.json()["choices"][0]["message"]["content"].strip()
    except httpx.HTTPStatusError as exc:
        logger.error(
            "OpenRouter ответил %s: %s", exc.response.status_code, exc.response.text[:300]
        )
        return None
    except httpx.RequestError as exc:
        logger.error("OpenRouter недоступен: %s", exc)
        return None
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        logger.error("Неожиданный ответ OpenRouter: %s", exc)
        return None
    except Exception:
        logger.exception("Ошибка правки текста")
        return None

    if not corrected or corrected == text:
        return None
    return corrected
