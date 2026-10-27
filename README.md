# Lazy to Text bot

Send a voice message to a Telegram bot and get the text back in the same chat.
The transcription happens on a separate worker, so the bot keeps answering
while it runs. The text comes back punctuated and capitalised, because the
recogniser itself is a model that writes sentences, not a stream of lowercase
words.

**Repository:** `lazy-to-text-bot` ·
**Live page:** [aa-blinov.github.io/lazy-to-text-bot](https://aa-blinov.github.io/lazy-to-text-bot/) ·
**Bot:** [@whisper_telegram_bot](https://t.me/whisper_telegram_bot)

[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![House style](https://github.com/aa-blinov/lazy-to-text-bot/actions/workflows/house-style.yml/badge.svg)](https://github.com/aa-blinov/lazy-to-text-bot/actions/workflows/house-style.yml)

![The project page](docs/screenshots/site.png)

---

## Quick start

Docker with Compose, a Telegram bot token, and the numeric Telegram id of
whoever is the administrator.

```bash
git clone https://github.com/aa-blinov/lazy-to-text-bot.git
cd lazy-to-text-bot
cp .env.example .env
docker compose up --build
```

Fill in `.env` before the first start:

```env
TELEGRAM_BOT_TOKEN=123456:replace-with-the-token-from-botfather
ADMIN_ID=123456789
```

Four containers start: `postgres` for the history, `redis` for the queue,
`lazy-to-text-bot` for the conversation, and `huey-worker` for the
transcription. The bot uses long polling, so the host needs no domain name and
no certificate.

`docker compose ps` shows `healthy` only when a container is actually ready:
the worker after both models have run, the bot after its profile is set. On a
cold start the worker is the last one to go healthy, because it downloads the
weights.

The first start downloads the ONNX weights into `data/hf`: 214 MB for the
Russian model and 107 MB for the English one. On a fast link that is about
30 seconds, and every start after that reads them from the volume. The worker
warms both models before it reports healthy, so a message that arrives during
the first start waits in the queue instead of failing. After the warm-up a
short voice message comes back in under a second.

The bot talks in Russian. The person it talks to picks the recognition
language, Russian or English, from the keyboard.

`ADMIN_ID` may be left empty: then the first person to send `/start` becomes
the administrator, and the log records it. Set it to pin the administrator
explicitly; several ids can be separated by commas.

The bot's name, description and avatar are set by the bot itself at start:
`Lazy to Text`, the description and the short description from
`app/bot/app.py`, and `app/assets/bot_avatar.png` as the picture (the same
icon the Lazy to Text desktop app uses). The avatar is uploaded only when the
profile has none; set `BOT_PROFILE_FORCE=1` to re-upload it after replacing
the file.

## What it does

- **Transcribes voice messages, video notes, audio files and video files.** A
  voice message, a round video message, an mp3/ogg/wav/flac/m4a document and
  an mp4/webm video all become text, in the language the user picked.
- **Never copies the file to disk.** The bot asks Telegram for the file URL
  and hands it to the worker; ffmpeg reads the stream over HTTPS and decodes
  it in memory. Nothing is written to the shared volume.
- **Writes with punctuation.** The Russian model is GigaAM v3 e2e, which emits
  punctuation, capital letters and normalised numbers by itself. No second
  punctuation step and no cloud call in the middle.
- **Answers in the same chat.** The reply lands under the message, and the
  status line under it is edited while the transcription runs. The transcript
  is a `<pre>` block, so every Telegram client offers its copy button.
- **Keeps answering while it works.** The audio is queued, and two worker
  threads share the loaded models, so a burst is absorbed instead of refused.
- **Remembers every request.** Each finished transcription is stored in
  Postgres with the time it took, the kind of media, the language and the text.
- **Keeps the list of allowed users.** The administrator adds a person by id,
  by `@username`, by forwarded message, or by tapping "Allow" on the request
  that arrives when somebody new sends `/start`.
- **Reports the numbers.** `/stats` gives the total number of users, and the
  active users, the number of requests and the number of new users for today
  and for the last seven days.

## Admin

Everything the administrator needs is behind `/admin`: one panel with the
list of allowed users, an add button, an invite link and the statistics.

Adding a person takes one message and one tap:

- send the numeric id, `123456789`;
- send the username, `@someone`;
- forward any message from that person — the id and the name come from the
  forwarded profile;
- or wait for their request: a person who writes `/start` without access
  sends you a card with **Allow** and **Deny**, and the allow is one tap.

Removing somebody is the same shape: the list is a set of buttons, a button
opens the person's card, and the card asks for confirmation. A person whose
access is removed gets a message saying so.

The `/invite` command gives the `https://t.me/<bot>` link to forward.

## How it works

```
voice message, round video, audio file or video file
  -> app/bot/handlers/media.py: ask Telegram for the file URL (getFile)
  -> Redis: Huey task transcribe_task(url, type, language)
  -> app/infra/queue.py -> app/infra/asr.py
       ffmpeg reads the URL over HTTPS -> 16 kHz mono float32
       GigaAM v3 e2e CTC (ONNX) on the CPU, 25 s chunks
  -> Redis: the result
  -> app/bot/handlers/media.py: the reply, then a row in Postgres
```

The bot and the worker are separate containers. Nothing is written to the
shared `data` volume for a request: the worker pulls the stream from Telegram
itself, so there is no download step in the bot and no file to clean up. The
`data` volume still holds the model cache for the worker.

The worker runs two threads in one process: `HUEY_WORKER_COUNT=2` and
`HUEY_WORKER_TYPE=thread`. Threads share the loaded models, so the second
worker costs memory for the audio buffer, not another 700 MB of weights. A
process worker would hold its own copy.

The bot waits for the result with `aget_result` and edits one status message
while it waits: "Получил запись…", then "Распознаю…". A long transcript is
split into several messages, because Telegram caps a message at 4096
characters.

The database is Postgres (`DATABASE_URL`, the `postgres` service in Compose).
It has two tables. `users` holds the allowed ids with their names, the chosen
language and the day they were added; `tasks` holds one row per finished
transcription: the timestamp, the duration, the kind of media, the language
and the text. Removing a person keeps their rows: the foreign key is
`ON DELETE SET NULL`. A database from an older release can be moved over with
`scripts/import_sqlite.py`.

## Capacity

Measured on two worker threads, with the stack under load:

| Load | Wall time | Last answer |
| --- | --- | --- |
| 8 clients, 12 s audio each | 3.3 s | 3.3 s |
| 20 clients, 12 s audio each | 10 s | 10 s |
| 10 clients, 58 s audio each | 20 s | 20 s |

A burst queues up instead of failing; the bot waits at least 120 seconds and
at most 900, depending on the duration the message reports. A
one-minute message takes 2.6 to 5 seconds of worker time depending on what
else runs on the host. To serve more at once, raise `HUEY_WORKER_COUNT`:
threads share the loaded models, process workers take about 700 MB each.

The Telegram side does not block: downloads happen inside the worker, and the
burst above held the bot event loop to about 40 ms of lag, all of it Postgres
writes. Postgres takes them without a lock and the pool is shared by the
process.

## Server sizing

Memory is flat, CPU is the variable. Measured on this host with the worker
pinned to a CPU quota to imitate a smaller server, two worker threads:

| vCPU | `ASR_THREADS` | 58 s audio | 20 clients, 12 s each | RAM |
| --- | --- | --- | --- | --- |
| 2 | 1 | 5.9 s | 14 s | 0.9 GB |
| 2 | 2 | 4.0 s | 15 s | 0.9 GB |
| 4 | 2 | 4.0 s | 11 s | 0.9 GB |
| 8+ | 0 (auto) | 2.6 to 4.9 s | 11 s | 0.9 GB |
| 2 | 0 (auto) | 19 s | 72 s | 0.9 GB |

The last row is the trap: `ASR_THREADS=0` lets onnxruntime open one thread per
core, and on a 2 vCPU box sixteen threads fight over two cores. Set
`ASR_THREADS=1` or `2` on a 2 vCPU server.

Where the 0.9 GB goes at idle and under load: worker 763 MB (the two ONNX
models, shared by both threads), bot 49 to 84 MB, Postgres 38 to 43 MB,
Redis 6 to 7 MB. The model is loaded once, so memory does not grow with the
number of requests; a 300-second buffer adds about 19 MB per running task.

Disk: the image is 1.1 GB, the model cache 318 MB, Postgres and Redis a few
hundred megabytes together.

- **Minimum:** 2 vCPU, 2 GB RAM, 20 GB SSD, `ASR_THREADS=1`. A minute of
  audio comes back in about 6 seconds, a burst of twenty short messages in 14.
- **Comfortable:** 4 vCPU, 4 GB RAM, `ASR_THREADS=2`. A minute in about 4
  seconds, the same burst in 11.
- **More than 8 vCPU buys little:** the work is already parallel inside the
  two workers, and memory stays under 1 GB.

## Configuration

Everything is an environment variable, read from `.env` when the process
starts. `.env.example` holds the same list with the values filled in.

| Variable | Default | What it does |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | none | The token from BotFather. Without it the bot logs the error and exits. |
| `ADMIN_ID` | none | Numeric Telegram id of the administrator, or several separated by commas. Empty means the first `/start` claims the role. |
| `DATABASE_URL` | `postgresql://lazy:lazy@postgres:5432/lazy` | Postgres connection string for the history. |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `lazy` | Credentials for the `postgres` service; keep them in step with `DATABASE_URL`. |
| `DATA_DIR` | `data` | Working directory of the worker; the image points `HF_HOME` at `/app/data/hf`, so the model cache lives in the `./data` volume. |
| `MAX_MEDIA_SECONDS` | `300` | The longest recording the bot accepts. |
| `REDIS_HOST` | `redis` | Queue host. Compose sets it to the service name. |
| `REDIS_PORT` | `6379` | Queue port. |
| `REDIS_DB` | `0` | Queue database number. |
| `RESULT_TTL_SECONDS` | `3600` | How long a result stays in Redis if nobody reads it. |
| `ASR_MODEL` | `gigaam-v3-e2e-ctc` | The ONNX model that handles Russian. |
| `ASR_MODEL_EN` | `whisper-base` | The ONNX model that handles English. |
| `ASR_QUANTIZATION` | `int8` | Weight precision; `int8`, `fp16` or empty for fp32. |
| `ASR_THREADS` | `0` | Threads per inference; `0` lets onnxruntime decide. |
| `WARM_UP_EN` | `1` | Warm the English model at worker start. `0` saves 107 MB of download, but the first English message waits for it. |
| `HF_TOKEN` | none | Optional Hugging Face token, for faster downloads. |
| `HUEY_WORKER_COUNT` | `1` | The number of worker threads. Set to 2 in `docker-compose.yml`. |
| `HUEY_WORKER_TYPE` | `thread` | The worker type. Threads share the models. |

Nothing talks to a cloud service beyond Telegram. The transcript goes from the
worker to the chat and into Postgres, and no third party sees it.

## Development

```bash
docker compose up --build                 # build the image, start the four services
docker compose run --rm huey-worker       # one worker, in the foreground
docker compose run --rm lazy-to-text-bot  # one bot, in the foreground
docker compose down                       # stop the four services
```

Without Docker:

```bash
pip install --no-cache-dir -r requirements.txt
python -m app.main
python -m app.worker.consumer
```

The package is imported as `app`, so the commands run from the repository
root (or from `/app` inside the container). `app/infra/queue.py` connects to
`REDIS_HOST` (default `redis`), so a run outside Compose needs that name to
resolve or an override in the environment. ffmpeg has to be on the path.

The repository has no test command. `tests/test_bot.py` is empty, and no test
runner is in `requirements.txt`. `scripts/smoke_flow.py` is the end-to-end
check that is actually run: it feeds real updates through the application
with the Telegram calls mocked and a real worker behind the queue, then
leaves a throwaway `lazy_smoke` database behind. The audio samples live in
`tests/fixtures/` and are part of the image, so a missing fixture fails the
run instead of silently skipping the worker.

| Path | What it holds |
| --- | --- |
| `app/main.py` | The composition root: settings, the database, the polling loop. |
| `app/container.py` | Builds the services from the settings. |
| `app/domain.py` | `User`, `Stats`, `Transcript`. |
| `app/bot/app.py` | Builds the application and registers the handlers. |
| `app/bot/texts.py` | Every string a person reads. |
| `app/bot/keyboards.py` | Buttons and keyboards. |
| `app/bot/handlers/` | `common`, `language`, `media`, `admin`, `requests`, `guards`. |
| `app/services/` | `access`, `transcription`, `stats`: the rules, without Telegram. |
| `app/infra/` | `database`, `asr`, `queue`: Postgres, ONNX, Huey. |
| `app/worker/consumer.py` | The worker entry point. |
| `Dockerfile` | Two stages on `python:3.12-slim`, with ffmpeg, libsndfile1 and libgomp1. |
| `docker-compose.yml` | The four services and the shared `./data` volume. |
| `scripts/smoke_flow.py` | The end-to-end check against a throwaway Postgres database. |
| `tests/fixtures/` | Short Russian, English and video samples plus a 58-second clip for the checks. |
| `scripts/import_sqlite.py` | One-time move of an older SQLite history into Postgres. |
| `.env.example` | The variables and their defaults. |

## License

MIT, © Alexander Blinov. See [LICENSE](LICENSE).
