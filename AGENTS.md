# AGENTS.md — agent context for `lazy-to-text-bot`

A Telegram bot that turns voice messages, video notes, audio files and video
files into text. Four containers: the bot, a Huey worker that runs GigaAM v3
on the CPU, Postgres for the history, and Redis for the queue. The interface
is Telegram, the replies are in Russian, and the code, the comments and the
docstrings are in Russian too.

## Run / build / test

```bash
docker compose up --build                  # build the image, start all four services
docker compose run --rm huey-worker        # one worker, in the foreground
docker compose run --rm lazy-to-text-bot   # one bot, in the foreground
docker compose down                        # stop the four services
pip install --no-cache-dir -r requirements.txt
python -m app.main                         # the bot, without Docker
python -m app.worker.consumer              # the worker, without Docker
```

The repository has no test command. `tests/test_bot.py` is empty, and no test
runner is in `requirements.txt`, so a change is checked by running the bot
against a real token. `python -m compileall app` is a syntax check the
standard library provides; it is not a project script.

Two things a run outside Compose needs. `app/infra/queue.py` reads
`REDIS_HOST` (default `redis`) and `REDIS_PORT` (default `6379`), and that
name has to resolve. `DATABASE_URL` has to point at a reachable Postgres.
ffmpeg has to be on the path: it decodes everything, including a Telegram URL
read over HTTPS.

## Where things live

| Path | What it holds |
| --- | --- |
| `app/main.py` | The composition root: settings, the schema, the polling loop. |
| `app/config.py` | One `Settings` object read from the environment. Nothing else calls `os.getenv`. |
| `app/domain.py` | `User`, `Stats`, `Transcript`: dataclasses with no infrastructure in them. |
| `app/container.py` | `build_services`: the one place where infrastructure is wired into the services. |
| `app/bot/app.py` | Builds the `Application`, registers handlers, sets the command menu. |
| `app/bot/texts.py` | Every string a person reads, in one place, with the escaping done there. |
| `app/bot/keyboards.py` | Button labels and keyboards, plus the label-to-handler constants. |
| `app/bot/formatting.py` | HTML escaping and splitting a long transcript. |
| `app/bot/deps.py` | Getters for the services stored in `bot_data`. |
| `app/bot/handlers/common.py` | `/start`, `/help`, `/cancel`, the fallback and the error handler. |
| `app/bot/handlers/guards.py` | "Is this an admin", and answers to button taps. |
| `app/bot/handlers/requests.py` | The access request card and the Allow/Deny decision. |
| `app/bot/handlers/media.py` | Voice, video note, audio and video: the file URL and the pipeline. |
| `app/bot/handlers/admin.py` | The panel, the list, the cards and the add conversation. |
| `app/bot/handlers/language.py` | The language menu and the choice. |
| `app/services/access.py` | Allowlist, admin roles, grant and revoke. No Telegram imports. |
| `app/services/transcription.py` | Enqueue a task, wait for the result, time out. |
| `app/services/stats.py` | Counters and the history row. |
| `app/infra/database.py` | The Postgres schema, the pool and the queries. |
| `app/infra/asr.py` | ONNX sessions, ffmpeg decoding (path or URL), 25 s chunking. |
| `app/infra/queue.py` | The Huey instance and `transcribe_task`. |
| `app/worker/consumer.py` | The worker entry point: logging, warm-up, Huey consumer. |
| `docs/` | The project page (`index.html`, `style.css`, `site.js`, fonts, `screenshots/`) and `architecture.md`. |
| `.github/workflows/pages.yml` | Deploys `docs/` to GitHub Pages on a push to `master`. |
| `tests/test_bot.py` | Empty. |
| `scripts/smoke_flow.py` | End-to-end handler and worker check against a throwaway database. |
| `tests/fixtures/` | Russian, English and video samples plus a 58-second clip; baked into the image. |
| `scripts/load_check.py` | Concurrent clients against the real queue: latency, loop lag, Redis keys. |
| `scripts/import_sqlite.py` | One-time move of an older SQLite history into Postgres. |
| `scripts/make_avatar.py` | Rebuilds the circle-safe avatar from the square icon. |
| `Dockerfile` | Two stages on `python:3.12-slim`, with ffmpeg, libsndfile1 and libgomp1. |
| `docker-compose.yml` | The four services, the `pgdata` volume and the shared `./data` volume. |
| `.env.example` | The variables and their default values. |

## Traps

- **The bot never downloads the file.** `handlers/media.py` calls `get_file`,
  takes `file_path` (a full URL with the bot token in it) and enqueues that.
  `app/infra/asr.py` hands the URL to ffmpeg, which streams and decodes in
  memory. There is no copy on disk and nothing to clean up. Consequence: the
  URL contains the token, so it must never be logged; ffmpeg repeats it in
  stderr, so `_scrub` replaces every URL with `<url>` before any log call, and
  `TimeoutExpired` is scrubbed too. It expires in about an hour, which is fine
  because the task starts immediately.
- **The duration limit for documents is checked after decoding.** Telegram
  gives a `document` no `duration`, so `Recognizer.transcribe_source` measures
  the decoded audio and returns the real length; `TranscriptTooLong` turns it
  into the same message the bot uses for voice messages.
- **Telegram gives bots files up to 20 MB.** `get_file` fails above that, so
  `handlers/media.py` checks `file_size` against `MAX_FILE_MB` (20 by default)
  first and answers with a clear message. A local Bot API server under the
  `local-api` profile lifts the cap to 2 GB: set `TELEGRAM_API_BASE`,
  `MAX_FILE_MB=2000` and `MAX_MEDIA_SECONDS=3600` together, and keep the
  `bot-api-data` volume mounted into the worker, which reads the file path
  `get_file` returns.
- **Refusals are logged.** Unsupported documents, oversized files and too
  long recordings write the user id, type, size and duration, so a report of
  "nothing happened" can be traced without guessing.
- **Any media type goes through the same path.** Voice, video note, `audio`,
  `document` with an audio or video MIME type or extension, and `video`. The
  document check is `_document_is_media`: a PDF gets "это не похоже на аудио
  или видео" instead of a download attempt.
- **GigaAM is Russian-only.** `app/infra/asr.py` answers an English request
  with a second model (`ASR_MODEL_EN`, `whisper-base` by default). Both are
  warmed at worker start (`WARM_UP_EN` turns the English one off), so no
  request ever waits for a download.
- **The model is downloaded on first start.** `HF_HOME` points at
  `/app/data/hf`, so the weights land in the volume and survive
  `docker compose down`. Measured: 214 MB for GigaAM plus 107 MB for
  `whisper-base`, about 26 to 30 seconds on a fast link; a warm start is 5 to
  6 seconds for both models.
- **The worker warms both models and then writes `/tmp/worker-ready`.** The
  compose healthcheck reads that file, so `healthy` means the model has
  actually run, not that the process started.
- **A chunk longer than 25 seconds is cut.** `app/infra/asr.py` splits the
  buffer at the quietest frame within two seconds of the limit, because the
  encoder was trained on 30-second windows. Chunks the model still rejects
  are halved.
- **The bot process must not import the model.** `app/infra/queue.py` imports
  the recogniser inside `transcribe_task`, and only
  `app/worker/consumer.py` calls `warm_up()`. Move either import to module
  level and both containers hold a copy of the session.
- **`ASR_THREADS` reaches onnxruntime through `SessionOptions`.** `0` means
  "let onnxruntime decide by core count"; the worker passes the value to
  `Recognizer`. On a 2 vCPU server set it to 1 or 2: with `0` the library
  opens a thread per visible core and sixteen threads fight over two cores
  (measured: a minute of audio took 19 s instead of 6).
- **Two worker threads share one process and one model.** The compose file
  sets `HUEY_WORKER_COUNT=2` and `HUEY_WORKER_TYPE=thread`. The entry point
  turns those variables into Huey's `-w` and `-k` flags, because Huey reads
  the command line, not the environment. With threads the second worker does
  not load another 700 MB of weights; with `process` it does.
- **The database is Postgres with a pool.** `app/infra/database.py` keeps one
  `ConnectionPool` per `DATABASE_URL` (1 to 8 connections) and hands out a
  connection per call; `with connect(...)` commits. The pool exists because
  the handler writes the history from the event loop and the queries must not
  serialise on one socket.
- **Removing a person keeps their history.** `tasks.user_id` is
  `ON DELETE SET NULL`, so the row stays without an owner and the counters in
  `/stats` do not lose past requests. Deleting the tasks instead would be a
  product change.
- **The queue result has a TTL and is deleted after the read.**
  `RedisExpireHuey` with `expire_time=RESULT_TTL_SECONDS` (3600) plus
  `TranscriptionService._discard` cover a task the bot stopped waiting for.
  Plain `RedisHuey` left a permanent hash key behind.
- **Redis evicts only keys with a TTL.** `--maxmemory 256mb
  --maxmemory-policy volatile-lru` means results (TTL) can be evicted, queued
  tasks (no TTL) cannot. AOF is on with `everysec`.
- **Nothing is dropped on restart.** `drop_pending_updates=False` in
  `app/main.py`: messages that arrived while the bot was down are processed
  after it starts.
- **The bot sets its own profile.** `post_init` writes the name, the
  description and the short description, and uploads
  `app/assets/bot_avatar.png`. The writes are conditional: Telegram
  rate-limits `setMyName` for about a day, and an unconditional call ended in
  `Flood control exceeded`. The getters return objects, so compare `.name`,
  `.description`, `.short_description`.
- **The avatar uploads with a raw multipart request.**
  `Bot.set_my_profile_photo` in python-telegram-bot 22.8 accepts a `file_id`
  or a URL only; `app/bot/app.py` posts the `attach://` form itself.
- **The avatar file is circle-safe.** Telegram crops the photo with a circle,
  so `app/assets/bot_avatar.png` is a full-bleed cream square with the
  microphone centred at 60% height. `scripts/make_avatar.py` rebuilds it.
- **A transcript containing HTML characters used to break the reply.** Every
  reply runs dynamic text through `html.escape` and the app-wide
  `parse_mode` is HTML; one reply was once killed by a single underscore.
- **The transcript is a `<pre>` block.** Telegram shows a copy button for
  code blocks, and a transcript is copied. `transcript_blocks` escapes first
  and splits the escaped text (`split_escaped`), because splitting first and
  escaping after grows the chunk past the 4096 limit when the text has many
  `<` or `&`. Raw `<` or an oversized chunk is a rejected message.
- **Admin handlers answer only in private chats.** `admin.build_handlers`
  wraps every command, callback and conversation step with `_private_only`:
  in a group `/admin` would otherwise post the whole allowlist with numeric
  IDs. A new admin handler has to go through `_guard` too.
- **Startup is strict on purpose.** `database.init_db` lets a connection
  error propagate and `consumer.py` exits when `warm_up` returns False, so
  Compose restarts the container instead of showing healthy. Both entry
  points delete the ready file at start, because `docker compose restart`
  keeps `/tmp` and a stale file would mark a broken process healthy.
- **The Telegram URL sits in Redis.** The token is in the task payload and
  therefore in the AOF, but Redis is not published, and the same token is
  already in the container environment. Rotating the token invalidates both
  copies; an auth-enabled Redis would be the next step if the host is shared.
- **The chosen language lives in Postgres.** It used to be
  `context.user_data["lang"]` and reset on every restart.

## Style / safety rails

- **The strings a person reads are in Russian, and the code matches them.**
  They all live in `app/bot/texts.py`; the keyboard buttons and the
  `filters.Regex` patterns are the same words, taken from one constant each.
- **Dependencies point one way.** `bot/handlers` import `bot/texts`,
  `bot/keyboards`, `bot/deps` and `services`; `services` import `infra` and
  `domain`; `infra` imports `config` and `domain`. Nothing under `services`
  or `infra` imports `bot`, and handlers never touch a database connection.
- **Every reply is HTML.** `Defaults(parse_mode=ParseMode.HTML)` is set once
  in `app/bot/app.py`.
- **The model stays on the CPU.** `onnxruntime` CPU wheels and
  `providers=["CPUExecutionProvider"]` are one decision written twice.
- **Every dependency is pinned.** A new dependency that needs a system
  library changes the Dockerfile too.
- **The `data/` layout is a contract.** It holds the model cache
  (`data/hf`); media is never written there.
- **The transcripts are personal data.** They are kept in Postgres and
  nowhere else: no cloud call takes them off the host.
- **Secrets come from the environment.** `.env` is in `.gitignore`, and
  `.env.example` holds placeholders rather than values.

## Where the product truth lives

`PRODUCT.md` holds it. Read it before changing the behaviour of the bot, and
write the change there when the behaviour changes.
