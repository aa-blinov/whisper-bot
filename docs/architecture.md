# Architecture

How lazy-to-text-bot is put together.

The bot is two processes and a queue. One process talks to Telegram and owns
the conversation; the other runs GigaAM v3 on the CPU. Redis carries the task
between them, and the `data/` directory carries the audio file.

For what the bot does and how to run it, read the
[README](../README.md). For the traps that cost a rebuild to learn, read
[AGENTS.md](../AGENTS.md).

## The shape

Four layers under `app/`, and the imports only ever point one way:

```
bot/       Telegram: handlers, texts, keyboards          (depends on services, domain)
services/  the rules: access, transcription, stats       (depends on infra, domain)
infra/     SQLite, ONNX, files, Huey                     (depends on config, domain)
domain.py  User, Stats, Transcript                       (depends on nothing)
```

`app/main.py` is the composition root: it reads `Settings`, opens the
database, builds the `Application` and starts polling. `app/worker/consumer.py`
is the second process: it warms the model and hands the task module to Huey.

| Layer | What it is responsible for |
| --- | --- |
| `app/domain.py` | `User`, `Stats`, `Transcript`. Plain dataclasses, no driver, no Telegram. |
| `app/container.py` | Builds the services from `Settings`; the only place that wires infrastructure in. |
| `app/bot/app.py` | Builds the `Application`, registers the handlers, sets the command menu. |
| `app/bot/handlers/` | One file per topic: `common`, `language`, `media`, `admin`, `requests`, `guards`. |
| `app/bot/texts.py` | Every string a person reads, with the escaping. |
| `app/bot/keyboards.py` | Button labels and keyboards. |
| `app/bot/deps.py` | Getters for the services stored in `bot_data`. |
| `app/services/access.py` | Allowlist, admin roles, grant and revoke, the language. |
| `app/services/transcription.py` | Enqueue the task, wait, time out, return a `Transcript`. |
| `app/services/stats.py` | The counters and the history row. |
| `app/services/media.py` | Downloaded files as a service, so the bot layer stays out of `infra`. |
| `app/infra/database.py` | The SQLite schema, the migrations and the queries. |
| `app/infra/asr.py` | The ONNX sessions, the audio decoding, the chunking. |
| `app/infra/media.py` | Where downloaded files go and how they are removed. |
| `app/infra/queue.py` | The Huey instance and `transcribe_task`. |

## The data flow

```
voice message or video note
  -> app/bot/handlers/media.py: download to data/<uuid hex>_<type>.bin
  -> app/services/transcription.py -> Redis: transcribe_task(path, type, language)
  -> app/infra/queue.py -> app/infra/asr.py
       soundfile (WAV/FLAC/OGG) or ffmpeg (MP4 and everything else)
       -> mono float32 at 16 kHz
       -> GigaAM v3 e2e CTC, 25 s chunks, quietest-frame cuts
  -> Redis: the result
  -> app/bot/handlers/media.py: the reply in the chat
```

The bot writes the file into `data/` and the worker deletes that exact path
after the transcription. The bot waits for the result with `aget_result` and
edits one status message while it waits; the wait is capped by
`asyncio.wait_for`, 120 seconds at the floor and 900 at the ceiling, because
the first message after a fresh deploy can arrive while the worker is still
warming the models.

The history is written after the reply is sent, one row per finished
transcription: the timestamp, the wall-clock duration, the kind of media, the
language and the text.

Nothing leaves the host. There is no correction call and no second model
between the recogniser and the chat: the text the worker returns is the text
the person reads.

## Decisions worth knowing about

### The model writes the punctuation

GigaAM v3 e2e is trained to emit sentence text: full stops, commas and
capital letters come out of the decoder, not out of a second model. That is
why there is no punctuation step and no "fix the text" call, and why the
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

The second cost is memory discipline: `app/infra/queue.py` imports the
recogniser inside the task, and only the worker entry point warms it up.
Moving either import to module level puts a session in the bot process too.

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

`app/bot/keyboards.py` holds each label once, and
`app/bot/handlers/admin.py` builds its `filters.Regex` from the same constant
with `re.escape`, anchored at both ends. Change a label and the handler
follows it; that is the whole point.

The older code used unanchored patterns on free text, so any message that
contained "Добавить пользователя" opened the add-user flow. Anchoring is what
closed it.

### Every reply is HTML

`Defaults(parse_mode=ParseMode.HTML)` is set once, and every dynamic value —
names, usernames, transcripts — goes through `html.escape`. The transcript
used to be wrapped in backticks with `parse_mode="Markdown"`, and a single
underscore in the recognised text made Telegram reject the message.

## Boundaries

- **Only `app/bot/` imports `telegram`.** The services, the infrastructure and
  the worker have no Telegram dependency at all.
- **Only `app/infra/database.py` writes SQL.** No other module opens a
  connection, and no handler touches the database directly.
- **Nothing talks to a third party.** There is no HTTP client in the code
  besides the one Telegram library brings.
- **Only `app/config.py` reads the environment.** Everything else receives a
  `Settings` object or a service built from it.
- **The worker never touches the database.** It returns the text and the
  language; the bot writes the row.
- **The imports point one way.** `bot` -> `services` -> `infra` -> `config`
  and `domain`. Nothing under `services/` or `infra/` imports `app.bot`, and
  a handler that needs data goes through a service.
- **The package is imported as `app`.** Run `python -m app.main` and
  `python -m app.worker.consumer` from the repository root, or from `/app`
  in the container; there are no top-level module imports left.
