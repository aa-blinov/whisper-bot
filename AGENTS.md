# AGENTS.md — agent context for `whisper-bot`

A Telegram bot that turns voice messages and video notes into text. Three
containers: the bot, a Huey worker that runs GigaAM v3 on the CPU, and Redis
for the queue. The interface is Telegram, the replies are in Russian, and the
code, the comments and the docstrings are in Russian too.

## Run / build / test

```bash
docker compose up --build                  # build the image, start redis, the bot and the worker
docker compose run --rm huey-worker        # one worker, in the foreground
docker compose run --rm telegram-stt-bot   # one bot, in the foreground
docker compose down                        # stop the three services
pip install --no-cache-dir -r requirements.txt
python app/bot.py                          # the bot, without Docker
python app/huey_consumer.py                # the worker, without Docker
```

The repository has no test command. `tests/test_bot.py` is empty, and no test
runner is in `requirements.txt`, so a change is checked by running the bot
against a real token. `python -m compileall app` is a syntax check the
standard library provides; it is not a project script.

Two things a run outside Compose needs. `app/tasks.py` reads `REDIS_HOST`
(default `redis`) and `REDIS_PORT` (default `6379`), and that name has to
resolve. ffmpeg has to be on the path: it decodes both the OGG/Opus of a
voice message and the MP4 of a video note.

## Where things live

| Path | What it holds |
| --- | --- |
| `app/bot.py` | Telegram handler wiring, the media pipeline and every reply a user sees. |
| `app/admin.py` | The admin panel, the access-request flow and the add/remove conversations. |
| `app/keyboards.py` | Button labels, reply keyboards and inline keyboards, plus `display_name`. |
| `app/config.py` | One `Settings` object read from the environment. Nothing else calls `os.getenv`. |
| `app/stt_processor.py` | ONNX sessions (GigaAM for Russian, Whisper for English), audio decoding, chunking. |
| `app/tasks.py` | The Huey instance: `RedisHuey("whisper-bot", …)` built from `Settings`. |
| `app/huey_tasks.py` | The `transcribe_task` the bot enqueues and the file deletion. |
| `app/huey_consumer.py` | The worker entry point: warm the model, then hand Huey the task module. |
| `app/database.py` | The SQLite schema, the migrations and the counters behind `/stats`. |
| `tests/test_bot.py` | Empty. |
| `Dockerfile` | Two stages on `python:3.12-slim`, with ffmpeg, libsndfile1 and libgomp1. |
| `docker-compose.yml` | The three services and the shared `./data` volume. |
| `.env.example` | The variables and their default values. |

## Traps

- **GigaAM is Russian-only.** `app/stt_processor.py` answers an English
  request with a second model (`ASR_MODEL_EN`, `whisper-base` by default),
  loaded lazily on the first such request. Do not remove that branch and
  keep the language button: before, the button only changed a number in the
  database and every model ignored it.
- **The model is downloaded on first start.** `HF_HOME` points at
  `/app/data/hf`, so the weights land in the same volume as the database and
  survive `docker compose down`. Without that variable huggingface_hub
  writes into the container's home directory and every rebuild downloads
  260 MB again.
- **A chunk longer than 25 seconds is cut.** `app/stt_processor.py` splits
  the buffer at the quietest frame within two seconds of the limit, because
  the encoder was trained on 30-second windows. Chunks the model still
  rejects are halved.
- **The bot process must not import the model.** `app/huey_tasks.py` imports
  `stt_processor` inside `transcribe_task`, and only `app/huey_consumer.py`
  calls `warm_up()`. Move either import to module level and both containers
  hold a copy of the session.
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
- **The reply keyboard is matched by Russian text.** `app/keyboards.py` holds
  the labels, and `app/admin.py` builds the regexes from the same constants
  with `re.escape`, anchored. A label that does not match its constant stops
  the button working.
- **The chosen language lives in SQLite, not in memory.** It used to be
  `context.user_data["lang"]` and reset on every restart.
  `database.set_language` is the only writer.
- **The foreign key on `tasks.user_id` is not enforced.** `PRAGMA
  foreign_keys` stays off, so removing a person leaves their request rows and
  the counters in `/stats` unchanged. Turning it on would make `remove_user`
  fail with `IntegrityError` instead of revoking access.
- **`created_at` is the day the person was added**, so "new users" in
  `/stats` counts real additions; older rows got the migration timestamp.
- **Telegram commands are set at start.** `_post_init` in `app/bot.py` calls
  `set_my_commands`, which is why a command added to the list shows up only
  after a restart.
- **A transcript containing HTML characters used to break the reply.** Every
  reply now runs dynamic text through `html.escape` and the application-wide
  `parse_mode` is HTML; do not reintroduce Markdown v1.

## Style / safety rails

- **The strings a person reads are in Russian, and the code matches them.**
  The keyboard buttons and the `filters.Regex` patterns are the same words,
  now taken from one constant each.
- **Every reply is HTML.** `Defaults(parse_mode=ParseMode.HTML)` is set once
  in `app/bot.py`.
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
