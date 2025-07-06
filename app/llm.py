import os
import json
import logging

from dotenv import load_dotenv

import httpx

logger = logging.getLogger(__name__)

load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL_NAME = os.getenv("OPENROUTER_MODEL_NAME")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
LLM_PROMPT_TEMPLATE = (
    "Исправь грамматические, пунктуационные ошибки и замени слова, если они не подходят по смыслу, в следующем тексте на русском языке. "
    "Если слово или фраза неуместны или не соответствуют контексту, замени их на более подходящие. "
    "Не добавляй лишней информации, не сокращай и не расширяй текст. Верни только исправленный текст, без каких-либо пояснений:\n\n{text}"
)


async def correct_text_with_llm(text: str) -> str:
    """
    Исправляет ошибки в тексте с помощью LLM через Openrouter API.
    Возвращает исправленный текст или оригинальный текст в случае ошибки.
    """
    if not OPENROUTER_API_KEY:
        logger.warning(
            "OPENROUTER_API_KEY не установлен. Пропускаем исправление текста через LLM."
        )
        return text

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENROUTER_MODEL_NAME,
        "messages": [
            {
                "role": "system",
                "content": "/no_think"
            },
            {
                "role": "user",
                "content": LLM_PROMPT_TEMPLATE.format(text=text),
            }
        ],
        "temperature": 0.1,
        "max_tokens": 2048,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                OPENROUTER_API_URL, headers=headers, json=payload
            )
            response.raise_for_status()

            response_data = response.json()
            corrected_text = response_data["choices"][0]["message"]["content"].strip()
            logger.info("Текст успешно исправлен через API Openrouter.")
            return corrected_text
    except httpx.RequestError as e:
        logger.error(f"Ошибка запроса к API Openrouter: {e}")
        return text
    except httpx.HTTPStatusError as e:
        logger.error(
            f"HTTP ошибка от Openrouter API: {e.response.status_code} - {e.response.text}"
        )
        return text
    except (KeyError, json.JSONDecodeError) as e:
        logger.error(f"Ошибка разбора ответа API Openrouter: {e}")
        logger.error(
            f"Ответ от API Openrouter: {response.text if 'response' in locals() else 'Нет ответа'}"
        )
        return text
    except Exception as e:
        logger.exception(f"Неизвестная ошибка при исправлении текста через LLM: {e}")
        return text
