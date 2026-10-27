# Product

<!-- impeccable:product-schema 1 -->

## Platform

adaptive

The bot lives inside Telegram, so the client is whatever the person already
has: the Telegram app on a phone, the desktop client, or the web client. The
deployment side is three Linux containers on one host: the bot, one worker,
and Redis.

## Users

A closed list of people who send voice messages to the bot and want the text
back. The administrator is the second audience: the one who adds those people
by id, removes them, and reads the numbers.

Nothing else is known. The GitHub description of the repository is empty, the
README names no audience, and there is no screenshot of a conversation
anywhere in the repository. What the code does say is that the group is small
enough for one person to administer by hand, one id at a time, that the
interface is in Russian, and that English is offered as a recognition
language.

## Product Purpose

The bot turns a voice message or a video note into text and puts the text
back under the message. That is the whole job.

The person using it is in a chat, holding a phone, and has just recorded a
thought. The bot turns that recording into something they can read, edit and
send on, without leaving the chat.

Success for the person: the transcript arrives in the same chat, with the
recognition mistakes taken out when a correction key is set. Success for the
product: the request is in the history with its duration and its text, and
`/stats` can tell the administrator how many requests came in today and over
the last seven days.

## Positioning

The transcription runs in a container the owner controls, on the CPU, with
the model cached on a disk the owner owns and the history in a SQLite file
that any SQLite client can read. A hosted transcription service cannot be
run that way.

The second difference is where the answer arrives. A desktop dictation
application puts the text into whatever window is in front of the person, and
a mobile one asks for a recording and an export. This one answers a message
that was sent to a bot, in the conversation where it was sent.

The third is how the deployment is put together: one host, three containers, a
bind mount for the data and a queue between the conversation and the CPU.
That is more machinery than a single script, and it is what keeps the bot
answering while the model is busy.

## Operating Context

The person using the bot is in Telegram, in a private chat with the bot, and
has just sent a voice message. The bot edits one status message under it
while the transcription runs, and replies with the transcript when it is
done. Nobody leaves the chat and nobody opens a second application.

The administrator is somewhere else, on the host, with Docker. They start the
three containers, they keep the token and the administrator id in `.env`, and
they add people to the allowlist by Telegram id. The allowlist is in SQLite,
and the bot refuses everybody who is not on it, including a person who has
just started a chat with it.

The deployment is long polling: the bot connects out to Telegram and asks for
updates. There is no incoming traffic, no domain name and no certificate to
keep.

## Capabilities and Constraints

Confirmed by the code:

- A voice message and a video note are transcribed, and nothing else is
  accepted.
- The recognition language is Russian or English, chosen by the person, and
  it falls back to Russian.
- The transcript arrives punctuated and capitalised: Russian is recognised by
  GigaAM v3 e2e CTC, which writes punctuation itself, and English by a second
  ONNX model.
- The transcription runs on the CPU with ONNX Runtime, on models cached in
  `data/hf`.
- The bot keeps answering while the transcription runs, because the work is
  on a Huey queue and the bot waits for the result.
- Nothing leaves the host. There is no correction by a language model and no
  cloud call: the transcript goes from the worker to the chat and to SQLite.
- Every finished transcription is stored with its timestamp, its wall-clock
  duration, the kind of media, the language and the text.
- The allowed people and the request history live in SQLite at `DB_PATH`.
- The administrator adds a person by numeric id, by `@username`, by forwarding
  one of their messages, or by tapping **Allow** on the request that arrives
  when a stranger writes `/start`. Removal is a button in the person's card,
  with a confirmation.
- The administrator reads the counters for today and for the last seven days
  from `/stats`.
- The bot is a long-polling Telegram bot, and the deployment is three
  containers: bot, worker, Redis.

Deliberately not true, and worth knowing before a change:

- There is no streaming and no partial result. The text arrives at the end,
  or it does not arrive.
- A failed transcription is not retried. The person is told to try later.
- The language is never detected. The person says which one it is.
- The duration in the history covers the whole round trip, not the length of
  the recording.
- The foreign key from `tasks.user_id` to `users.user_id` is not enforced, so
  removing a person leaves their rows behind.
- The repository carries no continuous integration, no working test and no
  screenshot. The one test file is empty.

## Brand Commitments

**Name:** Whisper STT bot. **Tone:** plain and technical, in Russian. The
replies say what happened: the file was received, the transcription is
running, the text was corrected, the text could not be recognised. They do
not congratulate anybody.

**Language:** the interface is Russian. The documents are English, because
they are read by whoever finds the link to the repository, and the two are
not meant to match word for word.

**Assets:** the bot avatar is the Lazy to Text icon (a teal microphone on a
cream rounded square), and the profile text lives in the BotFather fields set
by the code. The project page in `docs/` carries the same icon and the Monos
palette. There is no logo file of its own and no screenshot of a real
conversation.

## Evidence on Hand

- `README.md` describes the flow, the dependencies and the deployment.
- `docs/index.html` is the project page: what the bot does, the model, the
  admin flow and how to host it.
- `app/bot/handlers/media.py` holds the voice and video-note pipeline.
- `app/bot/handlers/admin.py` holds the panel, the access requests and the
  add/remove conversations.
- `app/bot/texts.py` holds every string a person reads.
- `app/infra/asr.py` holds the ONNX sessions, the audio decoding and the
  transcription.
- `app/infra/database.py` holds the schema, the migrations and the counters
  behind `/stats`.
- `requirements.txt` pins every dependency, and the Dockerfile installs
  ffmpeg, libsndfile1 and libgomp1.
- `docker-compose.yml` names the three services and the shared `./data`
  volume.
- `.env.example` holds the variables and their default values.
- The GitHub repository has one star, one fork, one watcher and one open
  issue, and its description is empty.

Absent, and not to be invented: no download counts, no usage numbers, no
testimonials, no comparison with other transcription bots, no screenshots, no
domain name.

The licence is claimed as MIT in the README. The repository carried no
`LICENSE` file before these documents; the MIT text was written at the same
time.

## Product Principles

1. **The text comes back in the same chat.** The person who sent the voice
   message gets the answer under it, without opening anything else.
2. **The CPU work belongs to the worker.** The bot process answers messages,
   queues audio and waits. A transcription that runs inside the bot process
   is a bug.
3. **Access is a list, and the administrator owns it.** A Telegram id is
   either in the database or the bot does nothing for that person.
4. **The transcript is the model's text, untouched.** Nothing rewrites it on
   the way out and nothing is sent to a third party to improve it. What the
   recogniser heard is what the person reads and what the history keeps.
5. **A failure is said out loud.** The queue failed, the text could not be
   recognised, an internal error happened. Each says so in the chat.

## Accessibility & Inclusion

- **The product is an accessibility tool.** Dictation is the whole point,
  and the person never types.
- **The answer is text.** The transcript arrives as a message, so it can be
  read aloud by a screen reader, copied and edited.
- **The administrator never types an id either.** The keyboard holds the
  commands, and the list of people to remove is a keyboard of ids.
- **The interface is Russian only.** A person who does not read Russian
  cannot use the keyboard, even with English recognition.
- **Not decided.** Nothing in the repository says which screen reader or
  which platform the transcript has been checked on, and the bot has no
  setting for the reply language, separately from the one used for the
  recognition.
