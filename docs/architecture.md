# Architecture

How whisper-bot is put together.

The bot is two processes and a queue. One process talks to Telegram and owns
the conversation; the other runs Faster-Whisper on the CPU. Redis carries the
task between them, and the `data/` directory carries the audio file.

For what the bot does and how to run it, read the
[README](../README.md). For the traps that cost a rebuild to learn, read
[AGENTS.md](../AGENTS.md).

## The shape

Seven modules under `app/`. The bot side imports the worker side, and the
worker side knows nothing about the bot.

| Module | What it is responsible for |
| --- | --- |
| `app/bot.py` | The Telegram handlers, the reply keyboards and every reply. The access check, the download, the wait for the result and the write to the history. |
| `app/tasks.py` | The Huey instance: `RedisHuey("whisper-bot", host="redis", port=6379, db=0, results=True)`. |
| `app/huey_tasks.py` | The `transcribe_task` the bot enqueues, and the deletion of the downloaded file after the transcription. |
| `app/huey_consumer.py` | The worker entry point. It puts `/app` on the path and hands Huey the task module. |
| `app/stt_processor.py` | The Whisper model, the conversion of a video note to MP3, and the transcription itself. |
| `app/llm.py` | The correction request to OpenRouter: the address, the prompt, the parameters and the fallback to the raw text. |
| `app/database.py` | The SQLite schema, the migration of the `users` table and the counters behind `/stats`. |

## The data flow

```
voice message or video note
  -> app/bot.py: download to data/<uuid hex>_<type>.bin
  -> Redis: transcribe_task(path, type, language)
  -> app/huey_tasks.py: stt_processor.transcribe_media_sync
       video note -> ffmpeg -> mp3 -> faster-whisper on the CPU
  -> Redis: the result
  -> app/bot.py: app/llm.py -> OpenRouter -> the reply in the chat
```

The bot writes the file into `data/` and the worker deletes that exact path
after the transcription. The bot waits for the result with `aget_result`,
polling with a backoff of 1.15 and a maximum delay of 1.0 second, and edits
one status message while it waits.

The correction is a single request to
`https://openrouter.ai/api/v1/chat/completions` with `temperature=0.1`,
`max_tokens=2048` and a timeout of 15 seconds. Any failure returns the raw
text, so the person who sent the message never learns that the correction
did not happen.

The history is written after the reply is sent, one row per finished
transcription: the timestamp, the wall-clock duration, the kind of media and
the text.

## Decisions worth knowing about

### The transcription runs in a second process

The bot hands the file to Redis and waits. A transcription that takes thirty
seconds does not stop the bot from answering the next message, and the
person sending the audio gets a status line rather than a frozen chat.

The cost is that the two containers have to meet twice: in Redis, and in the
`data/` directory through the bind mount `./data:/app/data`. If the mount is
missing on one side, the worker never finds the file and the bot waits for a
result that never arrives.

### The model stays on the CPU

`torch==2.7.1+cpu` in `requirements.txt` and the CPU wheel index in the
Dockerfile are the same decision written twice. The image is
`python:3.10.18-slim` with ffmpeg and libsndfile1.

What that costs is one copy of the model in memory per worker.
`docker-compose.yml` sets `HUEY_WORKER_COUNT=1` and
`HUEY_WORKER_TYPE=process`, and every worker process loads its own copy of
the Whisper model, so two workers hold two copies of it.

### The correction is optional and fails quietly

`app/llm.py` returns the text it was given when the key is missing, when the
request fails, when the status code is not 200 and when the answer has no
content. The caller compares the result with the raw text and only tells the
person that a correction happened when the two differ.

The cost is that a broken correction is invisible. The log is the only place
it shows, and the person receives a transcript that is no worse than the
recogniser's output.

### The reply keyboard is the interface, matched by words

The handlers use `filters.Regex` on the Russian text of the buttons, and the
patterns are unanchored. Any message that contains `Добавить пользователя`
runs the add-user handler, and a message made only of digits is caught by
the numeric handler before the language handlers see it.

The cost is that the label and the pattern have to be the same words. Change
one and change the other, or the button stops working.

### The downloaded file is always `.bin`

A voice message and a video note are both saved as
`data/<uuid hex>_<type>.bin`. The format is detected from the content, by
ffmpeg and by faster-whisper, so nothing breaks today. Anything that trusts
the extension will.

## Boundaries

- **Only `app/bot.py` imports `telegram`.** The worker side
  (`huey_tasks.py`, `stt_processor.py`) has no Telegram dependency at all.
- **Only `app/database.py` writes SQL.** No other module opens a connection,
  and the schema, the migration of the three name columns and the counters
  live in one file.
- **Only `app/llm.py` talks to OpenRouter.** The address and the prompt are
  constants there, and no other module knows that a correction exists.
- **The worker never touches the database.** It returns the text and the
  detected language; the bot writes the row.
- **The modules import each other by their top-level names.** `from tasks
  import huey`, `from stt_processor import transcribe_media_sync`, so `app/`
  has to be the directory the script is started from.
- **The queue host is a constant.** `app/tasks.py` connects to `host="redis"`,
  `port=6379`, `db=0`. No environment variable changes it.
