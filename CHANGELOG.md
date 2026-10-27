# Changelog

All notable changes to lazy-to-text-bot. Versions are ordered newest first.

<!--
  The format is Keep a Changelog. Each entry says what changed and why it
  was worth changing.

  The traps do not go here. They go in AGENTS.md, because the changelog is
  read by the people who use the software and the traps are read by whoever
  works on the code next.
-->

## [Unreleased]

### Removed

- **The OpenRouter correction layer is gone.** The recogniser writes finished
  text, so the extra request only added a third party, a timeout and a second
  thing that could fail without the person noticing. `app/llm.py`,
  `OPENROUTER_API_KEY`, `OPENROUTER_MODEL_NAME` and the `httpx` pin are
  removed; the transcript now goes from the worker straight to the chat and
  to SQLite. If a correction ever comes back, it comes back as a product
  decision, not as a config flag.

### Changed

- **The transcript arrives as a code block.** A message with a `<pre>` block
  has a copy button in every Telegram client, and a transcript is almost
  always copied. The text stays escaped, long answers are still split, and
  the page shows the same style.

- **The loading is now measurable and predictable.** The worker warms the
  Russian and the English models before it reports healthy, so a message sent
  during the first start waits in the queue instead of failing on a download:
  214 MB plus 107 MB, about 30 seconds once on a 9 MB/s link, then 5.5
  seconds for a warm start. A short voice message comes back in under a
  second and the wait now has a 120-second floor.
- **The avatar is circle-safe.** Telegram crops the profile photo with a
  circle, and the rounded-square app icon lost its corners there. The file is
  now a full-bleed cream square with the microphone centred at 60% height,
  built by `scripts/make_avatar.py`. The upload itself uses a raw multipart
  request, because `Bot.set_my_profile_photo` in python-telegram-bot 22.8
  takes a `file_id` or a URL only.
- **The README is the front door again.** The title is the product name, the
  live page and the bot are linked from the first lines, and the screenshot
  of the page sits under the badges.
- **The code is split into layers.** `app/domain.py` holds the dataclasses,
  `app/services` the rules (access, transcription, stats), `app/infra` SQLite,
  ONNX, files and the queue, and `app/bot` the Telegram side with the texts,
  the keyboards and one handler module per topic. Imports point one way, and
  `app/main.py` is the composition root next to `app/worker/consumer.py`.
  Entry points are `python -m app.main` and `python -m app.worker.consumer`.
- **The bot has a face.** The avatar is the Lazy to Text icon, the name is
  "Lazy to Text", and the description and short description are set from the
  profile: what the bot does and that the audio stays on its own server.
- **The replies read like a person wrote them.** All user-facing Russian text
  was rewritten: no long dashes, second person throughout, short lines, and
  the button labels are taken from the same constants the handlers match.

- **The recogniser is GigaAM v3 e2e CTC on ONNX Runtime**, and it writes the
  punctuation itself. The transcript now arrives with full stops, commas and
  capital letters without a second model, and an 11-second recording
  transcribes in about two seconds on a laptop CPU. Whisper, Torch,
  CTranslate2 and `pydub` are gone: the image installs `onnx-asr`,
  `onnxruntime`, `soundfile` and ffmpeg, and it builds in minutes.
- **The English option now picks a model.** GigaAM is Russian-only, so an
  English request goes to `ASR_MODEL_EN` (`whisper-base` by default), loaded
  on first use. Before, the language button changed a number that every model
  ignored.
- **Adding people became one flow instead of three commands.** The admin
  panel lists everybody as buttons; a person is added by numeric id, by
  `@username`, or by forwarding one of their messages, and every path ends in
  a card with a confirm button. A stranger who writes `/start` sends the
  administrator a card with **Allow** and **Deny**, so granting access is one
  tap.
- **Replies are HTML, not Markdown.** A transcript containing `_` used to be
  rejected by Telegram and reached the user as "внутренняя ошибка". Every
  dynamic value is escaped now, and a long transcript is split into several
  messages instead of failing the 4096-character limit.
- **The chosen language survives a restart.** It lives in `users.language`
  instead of `context.user_data`.
- **The queue address comes from the environment** (`REDIS_HOST`,
  `REDIS_PORT`, `REDIS_DB`) instead of a constant, and the model cache lives
  in the `data/` volume (`HF_HOME=/app/data/hf`) so a rebuild does not
  download 260 MB again.
- **The image is `python:3.12-slim`**, and the stale `python3.10` site-packages
  path in the Dockerfile is gone. `ADMIN_ID` accepts several ids separated by
  commas, and a non-numeric value no longer crashes the start.

### Added

- **The project has a page.** `docs/index.html` presents the bot: the
  conversation, the three steps, the admin flow, the model, privacy and the
  `docker compose` start. It follows the Monos kit, has no build step, and
  `.github/workflows/pages.yml` publishes `docs/` to GitHub Pages.
- **The administrator gets a panel**: `/admin` with the allowed users, the
  add button, the invite link and `/stats`.
- **`/invite`** returns the `https://t.me/<bot>` link to forward.
- **Access requests**: an unknown person's `/start` notifies every
  administrator with the id, the name and two buttons.
- **A model warm-up in the worker**, so the first voice message does not wait
  for the session to be built.
- **`scripts/smoke_flow.py`**: an end-to-end check of the handlers and the
  real worker, with only the Telegram calls mocked.

### Fixed

- **Profile updates stopped burning Telegram's rate limit.** Every start used
  to call `set_my_name` and the description setters unconditionally, and the
  API answered `Flood control exceeded. Retry in 71054 seconds`. The bot now
  reads each field and writes only when it differs.
- **The bot no longer loads a copy of the model.** `huey_tasks` imports the
  recognition module inside the task, so only the worker holds a session.
- **`/stats` counts real additions.** `users.created_at` exists, and "new
  users" is no longer a guess based on the first request.
- **A non-numeric `ADMIN_ID` no longer stops the bot at import.**
- **Video notes no longer go through an intermediate MP3.** ffmpeg decodes
  the track straight into 16 kHz mono audio.
- **`/remove_user` without arguments, the list and the removal share one
  list view**, and a removal asks for confirmation first.

## 0.1.0 — 2026

### Added

- The first release. A Telegram bot that turns voice messages and video notes
  into text, with a closed list of allowed users, a Huey worker, an optional
  OpenRouter correction and `/stats`.
