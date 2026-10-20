# AGENTS.md — agent context for `whisper-bot`

A Telegram bot that turns voice messages and video notes into text. Three
containers: the bot, a Huey worker that runs Faster-Whisper on the CPU, and
Redis for the queue. The interface is Telegram, the replies are in Russian,
and the code, the comments and the docstrings are in Russian too.

This file is what you need to work on the project without reading all of it.

## Run / build / test

```bash
docker compose up --build                 # build the image, start redis, the bot and the worker
docker compose run --rm huey-worker       # one worker, in the foreground
docker compose run --rm telegram-stt-bot   # one bot, in the foreground
docker compose down                       # stop the three services
pip install --no-cache-dir -r requirements.txt \
    --extra-index-url https://download.pytorch.org/whl/cpu
python app/bot.py                         # the bot, without Docker
python app/huey_consumer.py               # the worker, without Docker
```

The repository has no test command. `tests/test_bot.py` is empty, and no test
runner is in `requirements.txt`, so a change is checked by running the bot
against a real token. `python -m compileall app` is a syntax check the
standard library provides; it is not a project script.

Two things a run outside Compose needs. `app/tasks.py` connects to the Redis
host named `redis` on port 6379, and that name has to resolve. ffmpeg has to
be on the path, because pydub calls it for the video notes.

## Where things live

| Path | What it holds |
| --- | --- |
| `app/bot.py` | The Telegram handlers, the reply keyboards and every reply. The only file that imports `telegram`. |
| `app/tasks.py` | The Huey instance: `RedisHuey("whisper-bot", host="redis", port=6379, db=0, results=True)`. Three lines, and every one of them matters. |
| `app/huey_tasks.py` | The `transcribe_task` the bot enqueues, and the deletion of the file afterwards. |
| `app/huey_consumer.py` | The worker entry point. Eight lines, and the path fix belongs to the container layout. |
| `app/stt_processor.py` | The Whisper model, the audio conversion, the transcription. |
| `app/llm.py` | The correction request to OpenRouter, with the prompt and the address. |
| `app/database.py` | The SQLite schema, the migrations and the counters behind `/stats`. |
| `tests/test_bot.py` | Empty. |
| `Dockerfile` | Two stages on `python:3.10.18-slim`, with ffmpeg and libsndfile1 in the second one. |
| `docker-compose.yml` | The three services and the shared `./data` volume. |
| `.env.example` | The variables and their default values. |

## Traps

- **The bot process loads the Whisper model as well.** `app/bot.py` imports
  `huey_tasks`, which imports `stt_processor`, and `stt_processor` loads the
  model when it is imported. Both containers therefore hold a copy of the
  model in memory, and both download it on the first start. Uncouple the
  imports before anyone starts counting the memory.
- **A non-numeric `ADMIN_ID` stops the bot at import.** `app/bot.py` catches
  the conversion error and sets `ADMIN_ID` to `None`. `database.init_db`
  calls `int()` on the same variable with no guard, and the `ValueError` is
  not a `sqlite3.Error`, so it escapes. The bot dies before `main()` runs.
- **`duration_seconds` is wall-clock time, not the length of the audio.** It
  is measured from just before the Telegram download to the moment the result
  arrives, so it includes the download, the wait in the queue and the
  correction request. The number in the history measures the round trip, and
  it grows with the queue.
- **The queue host is a constant.** `app/tasks.py` connects to
  `host="redis"`, `port=6379`, `db=0`. That is the Compose service name, and
  no environment variable changes it.
- **The bot and the worker meet in the `data/` directory.** The bot writes
  `data/<uuid hex>_<type>.bin` and the worker deletes that exact path after
  the transcription. The two containers need the same bind mount, or the
  worker never finds the file and the bot waits for a result that never
  comes.
- **The extension of the downloaded file is `.bin` whatever the media is.**
  A Telegram voice message and a Telegram video note are both saved as
  `.bin`, and the extracted audio of a video note as `<path>.mp3`. The format
  is detected from the content, by ffmpeg and by faster-whisper, so nothing
  breaks today. Anything that trusts the extension will.
- **A transcript containing `_` breaks the reply.** The text is sent with
  `parse_mode="Markdown"` inside backticks, and `escape_md` is applied to
  the user list but not to the transcript. Telegram refuses the message, the
  generic handler catches the error, and the person sees the internal-error
  text. The request is not written to the history either, because the row is
  inserted after the reply.
- **The model cache is repaired once.** When the load fails at import,
  `stt_processor` deletes
  `data/whisper_models/models--Systran--faster-whisper-<model>` and tries
  again. The repair runs at import only, so a cache that stays broken is not
  deleted again until the container restarts.
- **The chosen language lives in memory.** `context.user_data["lang"]` holds
  `ru` or `en` and falls back to `ru`. It is never written to SQLite, so it
  resets when the bot restarts, and it is per user.
- **The reply keyboard is matched by Russian text.** The handlers use
  unanchored regular expressions, so any message containing
  `Добавить пользователя` runs the add-user handler, and a message made only
  of digits is caught by the numeric handler before the language handlers
  ever see it.
- **The foreign key on `tasks.user_id` is not enforced.** SQLite keeps
  foreign keys off unless the connection asks for them, and no connection
  here does. Removing a user leaves their request rows in the table.
- **"New users" in `/stats` means "first request".** The `users` table has
  no `created_at`, so the counters count the users whose first transcription
  falls inside the window.

## Style / safety rails

- **The strings a person reads are in Russian, and the code matches them.**
  The keyboard buttons and the `filters.Regex` patterns are the same words.
  Change one and change the other, or the button stops working.
- **The model stays on the CPU.** `torch==2.7.1+cpu` in `requirements.txt`
  and the CPU wheel index in the Dockerfile are one decision, written twice.
  A GPU build changes the size of the image and the memory budget.
- **Every dependency is pinned.** `httpx>=0.27.0` is the only range, and the
  extra index URL in the Dockerfile is part of the pin. A new dependency that
  needs a system library changes the Dockerfile too.
- **The `data/` layout is a contract.** `data/` holds the SQLite file, the
  downloaded media and the model cache, and the two containers share it
  through the bind mount.
- **The transcripts are personal data.** They are kept in
  `data/bot_database.db`, and when the correction is switched on they are
  sent to OpenRouter as well.
- **Secrets come from the environment.** `.env` is in `.gitignore`, and
  `.env.example` holds placeholders rather than values.

## Where the product truth lives

`PRODUCT.md` holds it. Read it before changing the behaviour of the bot, and
write the change there when the behaviour changes.
