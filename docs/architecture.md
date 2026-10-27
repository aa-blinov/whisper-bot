# Architecture

How whisper-bot is put together.

The bot is two processes and a queue. One process talks to Telegram and owns
the conversation; the other runs GigaAM v3 on the CPU. Redis carries the task
between them, and the `data/` directory carries the audio file.

For what the bot does and how to run it, read the
[README](../README.md). For the traps that cost a rebuild to learn, read
[AGENTS.md](../AGENTS.md).

## The shape

Ten modules under `app/`. The bot side imports the worker side, and the
worker side knows nothing about the bot.

| Module | What it is responsible for |
| --- | --- |
| `app/bot.py` | Handler wiring, the media pipeline, the access check, the wait for the result and the write to the history. |
| `app/admin.py` | The panel, the access requests, and the add/remove conversations. |
| `app/keyboards.py` | Every button label, the reply keyboards, the inline keyboards and `display_name`. |
| `app/config.py` | One `Settings` object built from the environment. |
| `app/tasks.py` | The Huey instance, built from `Settings`. |
| `app/huey_tasks.py` | The `transcribe_task` the bot enqueues, and the deletion of the downloaded file. |
| `app/huey_consumer.py` | The worker entry point: logging, the model warm-up, then Huey's consumer. |
| `app/stt_processor.py` | The ONNX sessions, the audio decoding, the chunking and the transcription. |
| `app/llm.py` | The optional correction request to OpenRouter. |
| `app/database.py` | The SQLite schema, the migrations and the counters behind `/stats`. |

## The data flow

```
voice message or video note
  -> app/bot.py: download to data/<uuid hex>_<type>.bin
  -> Redis: transcribe_task(path, type, language)
  -> app/huey_tasks.py: stt_processor.transcribe_media_sync
       soundfile (WAV/FLAC/OGG) or ffmpeg (MP4 and everything else)
       -> mono float32 at 16 kHz
       -> GigaAM v3 e2e CTC, 25 s chunks, quietest-frame cuts
  -> Redis: the result
  -> app/bot.py: app/llm.py (optional) -> OpenRouter -> the reply in the chat
```

The bot writes the file into `data/` and the worker deletes that exact path
after the transcription. The bot waits for the result with `aget_result` and
edits one status message while it waits; the wait is capped by
`asyncio.wait_for`, from 60 seconds upward depending on the recording.

The correction is a single request to
`https://openrouter.ai/api/v1/chat/completions` with `temperature=0.1`,
`max_tokens=2048` and a timeout of 20 seconds. Any failure returns `None`,
and the caller keeps the recogniser's text.

The history is written after the reply is sent, one row per finished
transcription: the timestamp, the wall-clock duration, the kind of media, the
language and the text.

## Decisions worth knowing about

### The model writes the punctuation

GigaAM v3 e2e is trained to emit sentence text: full stops, commas and
capital letters come out of the decoder, not out of a second model. That is
why the correction step is optional rather than load-bearing, and why the
Russian path needs exactly one ONNX session.

The cost is that the Russian path is Russian-only. English goes through
`ASR_MODEL_EN` (`whisper-base` by default), which is loaded on first use and
returns plainer text. The language button is therefore real: it picks the
model, not a decoder hint.

### The transcription runs in a second process

The bot hands the file to Redis and waits. A transcription that takes thirty
seconds does not stop the bot from answering the next message, and the person
sending the audio gets a status line rather than a frozen chat.

The cost is that the two containers have to meet twice: in Redis, and in the
`data/` directory through the bind mount `./data:/app/data`. If the mount is
missing on one side, the worker never finds the file and the bot waits for a
result that never arrives.

The second cost is memory discipline: `app/huey_tasks.py` imports the model
module inside the task, and only the worker entry point warms it up. Moving
either import to module level puts a session in the bot process too.

### The model stays on the CPU, and it is small

`onnxruntime` CPU wheels and `providers=["CPUExecutionProvider"]` are one
decision written twice. The image is `python:3.12-slim` with `ffmpeg`,
`libsndfile1` and `libgomp1`; there is no Torch, no CTranslate2 and no CUDA
anywhere.

What that buys: the image builds in minutes, the worker holds one 214 MB
model, and an 11-second Russian recording transcribes in about two seconds on
a laptop CPU. What it costs: no GPU, and one copy of the session per worker
process.

### Weights live in the volume, not in the image

`HF_HOME=/app/data/hf` in the Dockerfile points huggingface_hub at the bind
mount. A `docker compose down` and `up` therefore does not download 260 MB
again, and the image stays small enough to rebuild.

### Access is requested, then granted by one tap

A person who writes `/start` without access does not get a silent refusal.
The bot sends the administrator a card with the id, the name and two buttons;
`Allow` adds the row and sends the welcome, `Deny` closes the request. The
administrator can also add somebody by id, by `@username`, or by forwarding
one of their messages.

The cost is a fan-out to every administrator on every request, and a
`get_chat` call to turn an id into a name. A hidden-forward profile has no
`sender_user`, so that path falls back to asking for the id.

### The reply keyboard is matched by constants

`app/keyboards.py` holds each label once, and `app/admin.py` builds its
`filters.Regex` from the same constant with `re.escape`, anchored at both
ends. Change a label and the handler follows it; that is the whole point.

The older code used unanchored patterns on free text, so any message that
contained "Добавить пользователя" opened the add-user flow. Anchoring is what
closed it.

### Every reply is HTML

`Defaults(parse_mode=ParseMode.HTML)` is set once, and every dynamic value —
names, usernames, transcripts — goes through `html.escape`. The transcript
used to be wrapped in backticks with `parse_mode="Markdown"`, and a single
underscore in the recognised text made Telegram reject the message.

## Boundaries

- **`app/bot.py` and `app/admin.py` import `telegram`.** The worker side
  (`huey_tasks.py`, `stt_processor.py`) has no Telegram dependency at all.
- **Only `app/database.py` writes SQL.** No other module opens a connection.
- **Only `app/llm.py` talks to OpenRouter.**
- **Only `app/config.py` reads the environment.** Every other module imports
  `settings`.
- **The worker never touches the database.** It returns the text and the
  language; the bot writes the row.
- **The modules import each other by their top-level names.** `from tasks
  import huey`, `from stt_processor import transcribe_media_sync`, so `app/`
  has to be the directory the script is started from.
