# AGENTS.md — agent context for `lazy-to-text-bot`

A Telegram bot that turns voice messages and video notes into text. Three
containers: the bot, a Huey worker that runs GigaAM v3 on the CPU, and Redis
for the queue. The interface is Telegram, the replies are in Russian, and the
code, the comments and the docstrings are in Russian too.

## Run / build / test

```bash
docker compose up --build                  # build the image, start redis, the bot and the worker
docker compose run --rm huey-worker        # one worker, in the foreground
docker compose run --rm lazy-to-text-bot    # one bot, in the foreground
docker compose down                        # stop the three services
pip install --no-cache-dir -r requirements.txt
python -m app.main                         # the bot, without Docker
python -m app.worker.consumer              # the worker, without Docker
```

The repository has no test command. `tests/test_bot.py` is empty, and no test
runner is in `requirements.txt`, so a change is checked by running the bot
against a real token. `python -m compileall app` is a syntax check the
standard library provides; it is not a project script.

Two things a run outside Compose needs. `app/infra/queue.py` reads `REDIS_HOST`
(default `redis`) and `REDIS_PORT` (default `6379`), and that name has to
resolve. ffmpeg has to be on the path: it decodes both the OGG/Opus of a
voice message and the MP4 of a video note.

## Where things live

| Path | What it holds |
| --- | --- |
| `app/main.py` | The composition root: settings, the database, the polling loop. |
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
| `app/bot/handlers/media.py` | The voice/video-note pipeline. |
| `app/bot/handlers/admin.py` | The panel, the list, the cards and the add conversation. |
| `app/bot/handlers/language.py` | The language menu and the choice. |
| `app/services/access.py` | Allowlist, admin roles, grant and revoke. No Telegram imports. |
| `app/services/transcription.py` | Enqueue a task, wait for the result, time out. |
| `app/services/stats.py` | Counters and the history row. |
| `app/services/media.py` | Downloaded files as a service, so handlers never touch `infra`. |
| `app/infra/database.py` | The SQLite schema, the migrations and the queries. |
| `app/infra/asr.py` | ONNX sessions, audio decoding, 25 s chunking. |
| `app/infra/media.py` | Downloaded files: where they go and how they are removed. |
| `app/infra/queue.py` | The Huey instance and `transcribe_task`. |
| `app/worker/consumer.py` | The worker entry point: logging, warm-up, Huey consumer. |
| `docs/` | The project page (`index.html`, `style.css`, `site.js`, fonts, `screenshots/`) and `architecture.md`. |
| `.github/workflows/pages.yml` | Deploys `docs/` to GitHub Pages on a push to `master`. |
| `tests/test_bot.py` | Empty. |
| `scripts/smoke_flow.py` | End-to-end handler and worker check with only Telegram mocked. |
| `scripts/load_check.py` | Concurrent clients against the real queue: latency, loop lag, Redis keys. |
| `scripts/make_avatar.py` | Rebuilds the circle-safe avatar from the square icon. |
| `Dockerfile` | Two stages on `python:3.12-slim`, with ffmpeg, libsndfile1 and libgomp1. |
| `docker-compose.yml` | The three services and the shared `./data` volume. |
| `.env.example` | The variables and their default values. |

## Traps

- **GigaAM is Russian-only.** `app/infra/asr.py` answers an English
  request with a second model (`ASR_MODEL_EN`, `whisper-base` by default).
  Both are warmed at worker start (`WARM_UP_EN` turns the English one off),
  so no request ever waits for a download. Do not remove the English branch
  and keep the language button: the button would then change a number that
  every model ignores.
- **The model is downloaded on first start.** `HF_HOME` points at
  `/app/data/hf`, so the weights land in the same volume as the database and
  survive `docker compose down`. Measured on this machine: 214 MB for GigaAM
  plus 107 MB for `whisper-base`, about 30 seconds on a 9 MB/s link; a warm
  start is 5.5 seconds for both models. Without that variable
  huggingface_hub writes into the container's home directory and every
  rebuild downloads it all again.
- **The worker warms both models and then writes `/tmp/worker-ready`.** The
  compose healthcheck reads that file, so `healthy` means the model has
  actually run, not that the process started. `WARM_UP_EN=0` skips the
  English warm-up; the first English request then pays the 107 MB download
  inside its own timeout.
- **A chunk longer than 25 seconds is cut.** `app/infra/asr.py` splits
  the buffer at the quietest frame within two seconds of the limit, because
  the encoder was trained on 30-second windows. Chunks the model still
  rejects are halved.
- **The bot process must not import the model.**
  `app/infra/queue.py` imports the recogniser inside `transcribe_task`, and
  only `app/worker/consumer.py` calls `warm_up()`. Move either import to
  module level and both containers hold a copy of the session.
- **ONNX Runtime wants external weights as real sibling files.** GigaAM v3
  e2e CTC is a single `.onnx` file, so the hub cache is enough; a model that
  ships `.onnx.data` fails on a symlinked cache and needs a flattened
  directory. Check the file list before swapping the model.
- **`duration_seconds` is wall-clock time, not the length of the audio.** It
  is measured from just before the Telegram download to the moment the reply
  goes out, so it includes the download and the queue.
- **There is no language-model step, and adding one is a product change.**
  The transcript goes from the recogniser into the chat unchanged; the model
  already writes punctuation. A "fix the text" call would add a third party,
  a timeout and a second thing that can silently fail.
- **The database is WAL with one reused connection.** Opening a connection
  per call on the bind mount cost about 20 ms, and a plain fsync insert about
  29 ms; the handler runs in the event loop, so those milliseconds showed up
  as lag. With WAL, `synchronous=NORMAL` and a connection cached per path,
  an insert is 8 ms and a lookup 0.4 ms. `database.close_all()` exists for
  tests.
- **The result key has a TTL and is deleted after the read.** Ordinary
  `RedisHuey` writes results into a hash with no expiry, so a task the bot
  stopped waiting for left a permanent key. The queue is `RedisExpireHuey`
  (`expire_time=RESULT_TTL_SECONDS`, 3600 by default), and
  `TranscriptionService` deletes the key after a successful read.
- **One worker means one transcription at a time.** Measured: 20 clients with
  12-second clips finish in 23 seconds, 10 clients with 58-second clips in 29
  to 53 seconds, all answered. The bot waits up to 120 seconds, so roughly 45
  simultaneous minute-long messages would start timing out. Scale with
  `HUEY_WORKER_COUNT` and `HUEY_WORKER_TYPE=thread`: threads share the models,
  processes cost about 700 MB each.
- **The response loop never blocks on a download.** Telegram downloads are
  awaited, transcription is a separate process, and the only synchronous work
  in the loop is SQLite and the small Redis calls. Under the burst above the
  event loop stayed within 90 ms of lag.
- **The bot and the worker meet in the `data/` directory.** The bot writes
  `data/<uuid hex>_<type>.bin` and the worker deletes that exact path after
  the transcription. The two containers need the same bind mount.
- **The extension of the downloaded file is `.bin` whatever the media is.**
  Both the voice message and the video note are saved that way, and the
  format is detected from the content by soundfile and ffmpeg. Anything that
  trusts the extension will break.
- **`ADMIN_ID` may be empty.** Then the first person to send `/start` becomes
  the administrator — a deliberate fallback so a fresh deployment is usable,
  logged as a warning. Set `ADMIN_ID` (one id or several, comma-separated)
  to pin the administrator instead.
- **The reply keyboard is matched by Russian text.** `app/bot/keyboards.py`
  holds the labels, and `app/bot/handlers/admin.py` builds the regexes from
  the same constants with `re.escape`, anchored. A label that does not match
  its constant stops the button working.
- **The chosen language lives in SQLite, not in memory.** It used to be
  `context.user_data["lang"]` and reset on every restart.
  `database.set_language` is the only writer.
- **The foreign key on `tasks.user_id` is not enforced.** `PRAGMA
  foreign_keys` stays off, so removing a person leaves their request rows and
  the counters in `/stats` unchanged. Turning it on would make `remove_user`
  fail with `IntegrityError` instead of revoking access.
- **`created_at` is the day the person was added**, so "new users" in
  `/stats` counts real additions; older rows got the migration timestamp.
- **Telegram commands are set at start.** `post_init` in `app/bot/app.py`
  calls `set_my_commands`, which is why a command added to the list shows up
  only after a restart.
- **The bot sets its own profile.** The same `post_init` writes the name, the
  description and the short description, and uploads
  `app/assets/bot_avatar.png` as the avatar. The avatar goes up only when the
  profile has none, so after replacing the file set `BOT_PROFILE_FORCE=1`
  once; otherwise the old picture stays.
- **Profile writes are conditional, and that is not an optimisation.**
  Telegram rate-limits `setMyName` and `setMyDescription` for about a day:
  repeated starts with an unconditional `set_my_name` ended in `Flood control
  exceeded. Retry in 71054 seconds`. `_update_profile` reads each field and
  writes only when it differs; the getters return objects, so the comparison
  is against `.name`, `.description` and `.short_description`.
- **The avatar is uploaded with a raw HTTP multipart request.**
  `Bot.set_my_profile_photo` in python-telegram-bot 22.8 accepts a `file_id`
  or a URL only; passing a file makes the API answer "Field photo must be of
  type string". `app/bot/app.py` posts the same `attach://` form that
  BotFather does, with `httpx`, which is why that dependency is pinned.
- **The avatar file is circle-safe.** Telegram crops the profile photo with a
  circle, so `app/assets/bot_avatar.png` is a full-bleed cream square with
  the microphone centred at 60% height, not the rounded-square app icon with
  transparent corners. `scripts/make_avatar.py` rebuilds it from the icon.
- **A transcript containing HTML characters used to break the reply.** Every
  reply now runs dynamic text through `html.escape` and the application-wide
  `parse_mode` is HTML; do not reintroduce Markdown v1.

## Style / safety rails

- **The strings a person reads are in Russian, and the code matches them.**
  They all live in `app/bot/texts.py`; the keyboard buttons and the
  `filters.Regex` patterns are the same words, taken from one constant each.
- **Dependencies point one way.** `bot/handlers` import `bot/texts`,
  `bot/keyboards`, `bot/deps` and `services`; `services` import `infra` and
  `domain`; `infra` imports `config` and `domain`. Nothing under `services`
  or `infra` imports `bot`, and handlers never open SQLite directly.
- **Every reply is HTML.** `Defaults(parse_mode=ParseMode.HTML)` is set once
  in `app/bot/app.py`.
- **The transcript is a `<pre>` block.** Telegram shows a copy button for
  code blocks and a transcript is copied, so `formatting.transcript_blocks`
  wraps each chunk in `<pre>`, not in a quote. Keep the escaping and the
  splitting: a `pre` block with raw `<` or a chunk above 4096 characters is
  a rejected message.
- **The model stays on the CPU.** `onnxruntime` CPU wheels and
  `providers=["CPUExecutionProvider"]` are one decision written twice.
- **Every dependency is pinned.** A new dependency that needs a system
  library changes the Dockerfile too.
- **The `data/` layout is a contract.** It holds the SQLite file, the
  downloaded media and the model cache (`data/hf`).
- **The transcripts are personal data.** They are kept in
  `data/bot_database.db` and nowhere else: no cloud call takes them off the
  host.
- **Secrets come from the environment.** `.env` is in `.gitignore`, and
  `.env.example` holds placeholders rather than values.

## Where the product truth lives

`PRODUCT.md` holds it. Read it before changing the behaviour of the bot, and
write the change there when the behaviour changes.
