<!-- house-style: emoji-ok -->
<!-- The pictographs on the /stats screen are the product: they are what the
     administrator reads. app/bot/texts.py carries the same marker. -->

---
name: whisper-bot
description: A Telegram bot with no interface of its own. The surface is Telegram's reply keyboard, and every string the bot shows is in Russian.
colors:
  source: telegram-client
  primary: "#517da2"
  surface: "#ffffff"
  text: "#000000"
  text-muted: "#707579"
typography:
  source: telegram-client
  body:
    fontFamily: "the Telegram client's own face"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.35
  transcript:
    fontFamily: "the Telegram client's monospace face"
    fontSize: "16px"
    fontWeight: 400
rounded:
  source: telegram-client
  sm: "4px"
spacing:
  source: telegram-client
  sm: "4px"
---

# Design system: whisper-bot

This project has no visual identity of its own. It is a Telegram bot: the
keyboard, the colours, the type and the spacing all belong to the Telegram
client the person is reading in, and the bot has no stylesheet, no asset and
no theme file. What follows records what is on the screen, and what the bot
chooses out of it.

Product truth: [PRODUCT.md](PRODUCT.md). The interface in use:
[the architecture](docs/architecture.md).

## Overview

**Creative North Star: "The Chat Window"**

There is no chrome. The bot has no window of its own, no menu and no status
bar. Every screen it has is a message in a conversation, and the only control
surface is the reply keyboard Telegram draws under the input field. A change
that adds a visual layer to this project is a change to the wrong project.

The bot's own design decisions are about words and order rather than pixels:

- One job per message. The status line says what the bot is doing, and the
  answer is a separate message under the voice message it answers.
- The status line is edited in place. It never grows a second line and never
  adds a second message.
- The transcript is the product, and it is set in a code span so that the
  punctuation of speech recognition stays visible.
- The language of the interface is Russian, because the people who use the bot
  speak Russian. The recognition language is a separate thing and is chosen by
  the person who sends the audio.

**Key characteristics:**

- Nothing is drawn by the bot. Telegram draws every pixel.
- The keyboard is one column for a user and two for the administrator.
- The only screen with a layout of its own is `/stats`.
- A person who is not on the allowed list is refused in one sentence, with no
  keyboard at all.

## Colors

The bot sends no colour. The values in the frontmatter are Telegram's classic
light theme, recorded so that the screen is written down somewhere; a client
on another theme shows another palette, and that is the client's business.

- **Telegram blue** (`#517da2`): the colour of the client's own controls. It
  is never set by the bot.
- **Surface** (`#ffffff`) and **text** (`#000000`): the client's own pairing.
- **Muted text** (`#707579`): the colour Telegram uses for the second line of
  a bubble and for the hint under a button.

Two places in the bot do depend on how a message is rendered rather than on
what colour it is. A transcript is sent inside backticks, and Telegram draws
the span in its monospace face on a tinted ground. An id in the user list is
sent the same way, so a row of ids reads as code.

## Typography

The client's own face, at the client's own size. There is no web font, no
bundled file and no size the bot can ask for.

- **Body**: the proportional face of the client. Every sentence the bot
  writes is body text.
- **Transcript**: the monospace face. A transcript is one code span, so a
  line that the recogniser returned without punctuation still lines up.

The bot chooses `parse_mode="Markdown"` for the transcript, for the user list
and for the confirmation of an id. Nothing else carries a parse mode, and the
statistics screen carries none, because it uses pictographs instead.

## Layout

**The keyboard.** Telegram's reply keyboard, always `resize_keyboard=True`.
The administrator gets four buttons in two rows: `Язык` and
`Список пользователей` on the first, `Добавить пользователя` and
`Удалить пользователя` on the second. A user gets one button, `Язык`. The
language picker is a keyboard with `one_time_keyboard=True`, two rows,
`Русский` and `Английский`, and the current language marked with the suffix
` (выбран)`.

**The conversation.** The reply lands under the voice message it answers. The
status line sits above it and is edited in place four times:

1. `Получил медиа! Скачиваю файл...`
2. `Файл скачан. Запускаю транскрибацию...`
3. `Транскрибация завершена. Попытка исправить ошибки...`
4. `Текст исправлен. Отправляю ответ...`

A fourth state replaces the third when the correction changed nothing:
`Исправление текста не потребовалось или не удалось исправить. Отправляю
ответ...`.

**The statistics screen.** One message, no parse mode, four counters for
today and four for the last seven days. Each group is headed by a pictograph
and each line by a bullet:

```
📊 Статистика бота

👥 Всего пользователей: 12

📅 Сегодня (21.10.2026):
   • Активных: 4
   • Запросов на STT: 17
   • Новых: 1

📈 За последние 7 дней:
   • Активных: 9
   • Запросов на STT: 63
   • Новых: 5
```

The date is `DD.MM.YYYY`, from `datetime.now()` on the machine the bot runs
on.

## Components

### The status message

- One message, edited four times, never replaced by a new one.
- It is a plain sentence with an ellipsis, and the ellipsis says the work is
  still going.
- The transcript is not in it. The status line says what is happening; the
  answer says what was said.

### The language picker

- Two buttons, one per row, the current language marked with ` (выбран)`.
- It carries `one_time_keyboard=True`, so it disappears after the choice.
- The match is on the words `рус` and `англ`, not on the whole label, so a
  button with a suffix still matches.

### The user list

- One message, one line per user: a bullet, the id in a code span, the name
  escaped, and the handle in parentheses.
- The administrator is marked with ` (Админ)`.
- `escape_md` is applied to the name and the handle. It is not applied to the
  transcript.

### The transcript

- One code span, the whole text, under the voice message.
- The correction is applied before the span is built, so the answer is the
  corrected text or the raw text, never both.

### The refusal

- One sentence, no keyboard: `Извини, у тебя нет доступа к этому боту.
  Пожалуйста, свяжись с администратором, чтобы получить доступ.`
- The same sentence is used when the person is refused media, and the
  administrator gets a different one: `Извини, эта команда доступна только
  администратору.`

## Do's and Don'ts

### Do:

- **Do** keep the button label and the `filters.Regex` pattern the same
  words. The pattern is matched anywhere in the message, so `Добавить
  пользователя` in a sentence runs the handler.
- **Do** put the transcript in a code span and the ids in a code span, so the
  punctuation of the recogniser and the digits both stay readable.
- **Do** edit the status message in place, and keep it one sentence per
  state.
- **Do** write the interface in Russian, in every string a person reads.
- **Do** refuse a person who is not on the list in one sentence, with no
  keyboard attached.

### Don't:

- **Don't** send a transcript that has not been escaped. `escape_md` is
  applied to the user list and not to the transcript, and a literal `_` in a
  transcript makes Telegram refuse the message; the person sees the internal
  error text and the request is not written to the history either.
- **Don't** add a second status message, a progress bar or a percentage. The
  status line is one sentence.
- **Don't** put the correction and the raw text in the chat both. The bot
  sends one answer.
- **Don't** put a colour, a font or an icon in a message. The client owns
  those, and the statistics screen is the one place a pictograph belongs.
- **Don't** translate the interface to English. The people who use the bot
  speak Russian.
