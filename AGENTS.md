<!-- house-style: template — fill this file in, then delete this line -->

# AGENTS.md — agent context for `repo`

<!--
  The re-entry surface. Its job is to save the next session — human or
  agent — from rediscovering the project. Keep it skimmable: a reader who
  has to scroll twice has not found what they needed.

  Delete the sections that do not apply. Keep the ones that do.
-->

One line that says what this does.

## Run / build / test

```bash
echo 'replace with the install command'
echo 'replace with the test command'
echo 'replace with the build command'
```

<!--
  The exact commands, not the shapes of commands. A session that has to
  guess the difference between `npm test` and `npm run test:unit` will
  guess wrong.
-->

## Where things live

| Path | What it is |
| --- | --- |
| `src/` | The code. |
| `tests/` | The tests. |
| `scripts/` | Everything executable that is not source. |
| `docs/` | Guides and architecture. |

<!--
  The traps. The things that cost a rebuild to learn, written down so that
  the next person does not pay for them again.

  ## Traps

  - **The version lives in three places.** `pyproject.toml`, the CI
    workflow, and the README badge. They are compared by a test, and the
    test fails when they disagree.
  - **The worker process uses `spawn`, not `fork`.** A fixture patches
    `get_context`, not the module attributes, so patching the bare
    attributes will not intercept the call.
-->

## Style / safety rails

- **Comments explain *why*, never *what*.**
- **No emojis**, in any file. The house style bans them and the checker
  fails the build.
- **Do not add a dependency without a reason written down next to it.**
- **Do not remove functionality that looks intentional** — ask first.
