# Changelog

All notable changes to whisper-bot. Versions are ordered newest first.

<!--
  The format is Keep a Changelog. Each entry says what changed and why it
  was worth changing.

  The traps do not go here. They go in AGENTS.md, because the changelog is
  read by the people who use the software and the traps are read by whoever
  works on the code next.
-->

## [Unreleased]

### Changed

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
