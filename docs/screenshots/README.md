# Screenshots

There are no screenshots in this folder, and there is no image anywhere in the
repository. The bot has no interface of its own to capture: the whole surface
is Telegram's chat window and the reply keyboard the client draws.

## What stands in for a picture

The screens are written down instead, in [../../DESIGN.md](../../DESIGN.md):

- The reply keyboard, one column for a user and two for the administrator.
- The language picker, with the current language marked.
- The status message and the four states it is edited through.
- The transcript, sent as a code span under the voice message.
- The `/stats` screen, with its pictographs and its counters.

The strings are quoted from the code, so a reader can see exactly what a
person receives.

## Adding one

A capture of the chat belongs in this folder and is referenced by relative
path, the way the README does:

```markdown
![The reply keyboard](docs/screenshots/keyboard.png)
```

The checker resolves every image reference, so a file that is renamed without
its reference being updated fails the build. A capture of the chat contains
the names and the messages of real people, so it needs the same care as the
transcripts themselves.
