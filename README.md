# Whisper STT bot

Send a voice message to a Telegram bot and get the text back in the same chat.
The transcription happens on a separate worker, so the bot keeps answering
while it runs. With an OpenRouter key set, a language model fixes the
mistakes speech recognition makes before the text comes back.

[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## Quick start

Docker with Compose, a Telegram bot token, and the numeric Telegram id of
whoever is the administrator.

```bash
git clone https://github.com/aa-blinov/whisper-bot.git
cd whisper-bot
cp .env.example .env
docker compose up --build
```

Fill in `.env` before the first start:

```env
TELEGRAM_BOT_TOKEN=123456:replace-with-the-token-from-botfather
ADMIN_ID=123456789
```

Three containers start: `redis` for the queue, `telegram-stt-bot` for the
conversation, and `huey-worker` for the transcription. The bot uses long
polling, so the host needs no domain name and no certificate.

The first start downloads the Whisper model into `data/whisper_models`, and
every start after that reads it from there. The download needs the internet,
and a Hugging Face token makes it faster.

The bot talks in Russian. The person it talks to picks the recognition
language, Russian or English, from the keyboard.

Nobody else gets an answer until the administrator has added them by id. Start
a chat with the bot, send `/add_user`, then the numeric Telegram id, and the
next voice message is transcribed.

## What it does

- **Transcribes voice messages and video notes.** A voice message and a round
  video message both become text, in the language the user picked.
- **Answers in the same chat.** The reply lands under the message, and the
  status line under it is edited while the transcription runs.
- **Keeps answering while it works.** The audio is queued, so a slow
  transcription never blocks the next message.
- **Corrects the transcript when it can.** With `OPENROUTER_API_KEY` set, the
  raw text goes to a model on OpenRouter that is asked to fix recognition and
  punctuation errors and to change nothing else. Without the key the raw text
  is returned.
- **Remembers every request.** Each finished transcription is stored in SQLite
  with the time it took, the kind of media and the text itself.
- **Keeps the list of allowed users.** The administrator adds a person by id
  and removes one the same way. Everybody else is refused.
- **Reports the numbers.** `/stats` gives the total number of users, and the
  active users, the number of requests and the number of new users for today
  and for the last seven days.

## How it works

```
voice message or video note
  -> app/bot.py: download to data/<uuid hex>_<type>.bin
  -> Redis: Huey task transcribe_task(path, type, language)
  -> app/huey_tasks.py: stt_processor.transcribe_media_sync
       video note -> ffmpeg -> mp3 -> faster-whisper on the CPU
  -> Redis: the result
  -> app/bot.py: app/llm.py -> OpenRouter -> the reply in the chat
```

The bot and the worker are separate containers, and they meet twice: in the
`data` directory, where the bot leaves the downloaded file and the worker
deletes it after the transcription, and in Redis, where the task and its
result travel.

The worker is one process by default. `docker-compose.yml` sets
`HUEY_WORKER_COUNT=1` and `HUEY_WORKER_TYPE=process`, and every worker
process loads its own copy of the Whisper model, so the number of workers is
also the number of copies of the model in memory.

A voice message goes to Faster-Whisper as it was downloaded. A video note is
converted to MP3 with pydub, which calls ffmpeg, and the MP3 is deleted right
after the transcription.

The bot waits for the result with `aget_result` and edits one status message
while it waits: "Получил медиа! Скачиваю файл...", then "Файл скачан.
Запускаю транскрибацию...", then "Транскрибация завершена. Попытка исправить
ошибки...".

The correction is one request to `https://openrouter.ai/api/v1/chat/completions`
with `temperature=0.1`, `max_tokens=2048` and a timeout of 15 seconds. Any
failure returns the raw text, and the person sending the message never sees
the difference.

The database is SQLite, at `DB_PATH` or `data/bot_database.db`. It has two
tables. `users` holds the allowed ids with their names, and `tasks` holds one
row per finished transcription: the timestamp, the duration, the kind of
media and the recognised text. An older database gains the three name columns
on the next start.

## Configuration

Everything is an environment variable, read from `.env` when the process
starts. `.env.example` holds the same list with the values filled in.

| Variable | Default | What it does |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | none | The token from BotFather. Without it the bot logs the error and exits. |
| `ADMIN_ID` | none | The numeric Telegram id of the administrator. Every admin command stays closed without it. |
| `DB_PATH` | `data/bot_database.db` | The SQLite file, relative to the working directory. |
| `WHISPER_MODEL` | `small` | The Faster-Whisper model. |
| `WHISPER_COMPUTE_TYPE` | `int8` | The compute type CTranslate2 runs. |
| `WHISPER_BEAM_SIZE` | `5` | The beam size of the decoder. |
| `WHISPER_CPU_THREADS` | `10` | The threads CTranslate2 uses. |
| `WHISPER_NUM_WORKERS` | `1` | The CTranslate2 workers. |
| `HF_TOKEN` or `HUGGING_FACE_HUB_TOKEN` | none | The Hugging Face token. Either name works, and both are exported to the Hub. |
| `OPENROUTER_API_KEY` | none | The key for the correction request. Without it the raw text is returned. |
| `OPENROUTER_MODEL_NAME` | none | The model that does the correction. `.env.example` sets `openai/gpt-oss-20b:free`. |
| `HUEY_WORKER_COUNT` | `1` | The number of worker processes. Set in `docker-compose.yml`. |
| `HUEY_WORKER_TYPE` | `process` | The worker type. Set in `docker-compose.yml`. |

Three things are not variables. The address of the OpenRouter API and the
prompt that asks for the correction are constants in `app/llm.py`, and the
Redis host `redis` on port 6379 is a constant in `app/tasks.py`.

## Development

```bash
docker compose up --build                 # build the image, start the three services
docker compose run --rm huey-worker       # one worker, in the foreground
docker compose run --rm telegram-stt-bot   # one bot, in the foreground
docker compose down                       # stop the three services
```

Without Docker:

```bash
pip install --no-cache-dir -r requirements.txt \
    --extra-index-url https://download.pytorch.org/whl/cpu
python app/bot.py
python app/huey_consumer.py
```

The modules import each other by their top-level names, so `app/` has to be
the directory the script is started from. `app/tasks.py` connects to the
Redis host named `redis`, so a run outside Compose needs that name to
resolve, and ffmpeg has to be on the path for the video notes.

The repository has no test command. `tests/test_bot.py` is empty, and no test
runner is in `requirements.txt`.

| Path | What it holds |
| --- | --- |
| `app/bot.py` | The Telegram handlers, the keyboards and the replies. |
| `app/tasks.py` | The Huey instance and the Redis connection. |
| `app/huey_tasks.py` | The task the bot enqueues. |
| `app/huey_consumer.py` | The worker entry point. |
| `app/stt_processor.py` | The model, the audio conversion and the transcription. |
| `app/llm.py` | The correction request. |
| `app/database.py` | The SQLite schema and the queries behind `/stats`. |
| `Dockerfile` | Two stages on `python:3.10.18-slim`, with ffmpeg and libsndfile1. |
| `docker-compose.yml` | The three services and the shared `./data` volume. |
| `.env.example` | The variables and their defaults. |

## License

MIT, © Alexander Blinov. See [LICENSE](LICENSE).
