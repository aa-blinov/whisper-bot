# Whisper STT bot

Send a voice message to a Telegram bot and get the text back in the same chat.
The transcription happens on a separate worker, so the bot keeps answering
while it runs. The text comes back punctuated and capitalised, because the
recogniser itself is a model that writes sentences, not a stream of lowercase
words.

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

The first start downloads the GigaAM v3 ONNX weights into `data/hf`, and
every start after that reads them from there. The download is about 260 MB
and needs the internet once.

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

- **Transcribes voice messages and video notes.** A voice message and a round
  video message both become text, in the language the user picked.
- **Writes with punctuation.** The Russian model is GigaAM v3 e2e, which emits
  punctuation, capital letters and normalised numbers by itself. No second
  punctuation step and no cloud call in the middle.
- **Answers in the same chat.** The reply lands under the message, and the
  status line under it is edited while the transcription runs.
- **Keeps answering while it works.** The audio is queued, so a slow
  transcription never blocks the next message.
- **Remembers every request.** Each finished transcription is stored in SQLite
  with the time it took, the kind of media, the language and the text.
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
voice message or video note
  -> app/bot/handlers/media.py: download to data/<uuid hex>_<type>.bin
  -> Redis: Huey task transcribe_task(path, type, language)
  -> app/infra/queue.py -> app/infra/asr.py
       soundfile or ffmpeg -> 16 kHz mono float32
       GigaAM v3 e2e CTC (ONNX) on the CPU, 25 s chunks
  -> Redis: the result
  -> app/bot/handlers/media.py: the reply in the chat
```

The bot and the worker are separate containers, and they meet twice: in the
`data` directory, where the bot leaves the downloaded file and the worker
deletes it after the transcription, and in Redis, where the task and its
result travel.

The worker is one process by default. `docker-compose.yml` sets
`HUEY_WORKER_COUNT=1` and `HUEY_WORKER_TYPE=process`, and every worker
process loads its own copy of the model, so the number of workers is also the
number of copies of the model in memory.

A voice message and a video note go through the same path: the file is saved
as `.bin`, and ffmpeg finds the audio track inside whatever the container is.
There is no intermediate MP3 and no `pydub`.

The bot waits for the result with `aget_result` and edits one status message
while it waits: "Скачиваю запись…", then "Распознаю речь…". A long transcript
is split into several messages, because Telegram caps a message at 4096
characters.

The database is SQLite, at `DB_PATH` or `data/bot_database.db`. It has two
tables. `users` holds the allowed ids with their names, the chosen language
and the day they were added; `tasks` holds one row per finished transcription:
the timestamp, the duration, the kind of media, the language and the text. An
older database gains the missing columns on the next start.

## Configuration

Everything is an environment variable, read from `.env` when the process
starts. `.env.example` holds the same list with the values filled in.

| Variable | Default | What it does |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | none | The token from BotFather. Without it the bot logs the error and exits. |
| `ADMIN_ID` | none | Numeric Telegram id of the administrator, or several separated by commas. Empty means the first `/start` claims the role. |
| `DB_PATH` | `data/bot_database.db` | The SQLite file, relative to the working directory. |
| `DATA_DIR` | `data` | Where downloaded media and the model cache live. |
| `MAX_MEDIA_SECONDS` | `300` | The longest recording the bot accepts. |
| `REDIS_HOST` | `redis` | Queue host. Compose sets it to the service name. |
| `REDIS_PORT` | `6379` | Queue port. |
| `REDIS_DB` | `0` | Queue database number. |
| `ASR_MODEL` | `gigaam-v3-e2e-ctc` | The ONNX model that handles Russian. |
| `ASR_MODEL_EN` | `whisper-base` | The ONNX model that handles English. |
| `ASR_QUANTIZATION` | `int8` | Weight precision; `int8`, `fp16` or empty for fp32. |
| `ASR_THREADS` | `4` | Threads onnxruntime may use. |
| `HF_TOKEN` | none | Optional Hugging Face token, for faster downloads. |
| `HUEY_WORKER_COUNT` | `1` | The number of worker processes. Set in `docker-compose.yml`. |
| `HUEY_WORKER_TYPE` | `process` | The worker type. Set in `docker-compose.yml`. |

Nothing talks to a cloud service. The transcript goes from the worker to the
chat and into SQLite, and no third party sees it.

## Development

```bash
docker compose up --build                 # build the image, start the three services
docker compose run --rm huey-worker       # one worker, in the foreground
docker compose run --rm telegram-stt-bot  # one bot, in the foreground
docker compose down                       # stop the three services
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
with the Telegram calls mocked and a real worker behind the queue.

| Path | What it holds |
| --- | --- |
| `app/main.py` | The composition root: settings, the database, the polling loop. |
| `app/container.py` | Builds the services from the settings. |
| `app/domain.py` | `User`, `Stats`, `Transcript`. |
| `app/bot/app.py` | Builds the application and registers the handlers. |
| `app/bot/texts.py` | Every string a person reads. |
| `app/bot/keyboards.py` | Buttons and keyboards. |
| `app/bot/handlers/` | `common`, `language`, `media`, `admin`, `requests`, `guards`. |
| `app/services/` | `access`, `transcription`, `stats`, `media`: the rules, without Telegram. |
| `app/infra/` | `database`, `asr`, `media`, `queue`: SQLite, ONNX, files, Huey. |
| `app/worker/consumer.py` | The worker entry point. |
| `Dockerfile` | Two stages on `python:3.12-slim`, with ffmpeg, libsndfile1 and libgomp1. |
| `docker-compose.yml` | The three services and the shared `./data` volume. |
| `.env.example` | The variables and their defaults. |

## License

MIT, © Alexander Blinov. See [LICENSE](LICENSE).
