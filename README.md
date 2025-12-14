# Whisper Telegram STT Bot

## Overview

**Whisper Telegram STT Bot** is an asynchronous Python Telegram bot for automatic speech-to-text conversion of voice messages and video notes using Faster-Whisper. It leverages a scalable task queue powered by Huey and Redis for fast, non-blocking processing. The bot supports user access control, request history, and optional automatic text correction via LLM.

## Features

- **Speech-to-Text**: Converts Telegram voice messages and video notes to text.
- **Async Task Queue**: Asynchronous processing with Huey (Redis) so the bot remains responsive.
- **User Management**: Admin can add/remove users and view the allowed user list.
- **Text Correction**: Optional LLM integration for automatic text correction.
- **Persistent Storage**: Stores user and request history in SQLite.
- **Dockerized**: Full Docker and Docker Compose support for easy deployment.

## Dependencies

- **python-telegram-bot**: Telegram Bot API
- **faster-whisper**: Fast and accurate speech recognition
- **huey**: Task queue
- **redis**: Queue backend
- **pydub**: Audio/video processing
- **python-dotenv**: Environment variable loading
- **torch, torchaudio**: Required for Whisper

## How It Works

1. **User** sends a voice message or video note to the bot.
2. **Bot** saves the file to the shared `data/` folder and enqueues a transcription task in Huey.
3. **Huey worker** processes the task asynchronously using Faster-Whisper and deletes the file after processing.
4. **Bot** receives the result, optionally corrects the text via LLM, and sends it back to the user.
5. **Admin** can manage users via commands and the admin keyboard.

## Getting Started

### Prerequisites

- Docker and Docker Compose
- Telegram Bot Token

### Installation & Run

1. Clone the repository:

   ```sh
   git clone <repo-url>
   cd whisper-bot
   ```

2. Create a `.env` file (example):

   ```env
   TELEGRAM_BOT_TOKEN=your_bot_token
   ADMIN_ID=your_telegram_id
   DB_PATH=data/bot_database.db
   WHISPER_MODEL=small
   WHISPER_COMPUTE_TYPE=int8
   HF_TOKEN=your_huggingface_token  # Опционально: для более быстрой загрузки моделей
   OPENROUTER_API_KEY=your_bot_openrouter_api_token
   OPENROUTER_MODEL_NAME=your_favorite_model_name
   ```

3. Start all services:

   ```sh
   docker-compose up --build
   ```

### Usage

- Just send a voice message or video note to the bot — you'll get the transcribed text in reply.
- Use admin commands and keyboard to manage users.
- Don't forget to give the bot access to your Telegram account by starting a chat with it.

### Useful Commands

- Stop all services:

  ```sh
  docker-compose down
  ```

- Run only the worker:

  ```sh
  docker-compose run --rm huey-worker
  ```

- Run only the bot:

  ```sh
  docker-compose run --rm telegram-stt-bot
  ```

## Project Structure

```text
app/
  bot.py            # Telegram bot logic
  database.py       # SQLite database logic
  huey_consumer.py  # Huey worker entrypoint
  huey_tasks.py     # Huey task definitions
  llm.py            # LLM-based text correction
  stt_processor.py  # Whisper and audio processing
  tasks.py          # Huey initialization
.env
.env.example
docker-compose.yml
Dockerfile
README.md
requirements.txt
```

## Contributing

Pull requests and suggestions are welcome! Please open an issue or submit a PR to help improve the project.

## License

This project is licensed under the MIT License. See the [LICENSE](https://opensource.org/license/mit) file for details.
