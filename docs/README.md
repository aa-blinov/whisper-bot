# Documentation

The documents for lazy-to-text-bot, and the page that presents it.

| Document | What it covers |
| --- | --- |
| [index.html](index.html) | The project page: what the bot does, the model, the admin flow, how to host it. Published to [aa-blinov.github.io/lazy-to-text-bot](https://aa-blinov.github.io/lazy-to-text-bot/). |
| [architecture.md](architecture.md) | How the bot is put together: the layers, the data flow and the boundaries. |
| [screenshots/chat.svg](screenshots/chat.svg) | The diagram on the page: voice, queue, worker, reply, history. |
| [../README.md](../README.md) | The front door: what the bot does and how to run it. |
| [../AGENTS.md](../AGENTS.md) | The commands, the traps and the rails for a session that opens the repository. |
| [../PRODUCT.md](../PRODUCT.md) | The product truth the code is measured against. |
| [../DESIGN.md](../DESIGN.md) | The visual system: the keyboard, the messages and the statistics. |

## The page

`index.html` is one static file with `style.css`, `site.js`, two woff2 files
and the favicon next to it. No build step and no package manager: GitHub Pages
serves `docs/` as it is, and `.github/workflows/pages.yml` deploys it on every
push to `master` that touches this folder.

The page follows the Monos kit: warm paper, one 6px radius, one face, text
buttons and hairlines. The colour roles are the kit's Gruvbox light and dark
values, written once in `style.css`; components never hold a raw colour. The
two woff2 files are JetBrains Mono under the SIL Open Font License, see
[fonts/LICENSE-jetbrains-mono.txt](fonts/LICENSE-jetbrains-mono.txt).

To preview it locally, open `docs/index.html` in a browser. There is no server
to start.

## Reading order

New here: [../README.md](../README.md), then [architecture.md](architecture.md).

Changing the bot: [architecture.md](architecture.md), then
[../AGENTS.md](../AGENTS.md) for the traps. The interface is described in
[../DESIGN.md](../DESIGN.md), and the strings a person reads are in Russian
in both the code and the document.

## What is not here

There is no guide for the deployment beyond the `docker-compose.yml` in the
root, and there is no test guide: the repository has no test command and
`tests/test_bot.py` is empty. The smoke check in
[../scripts/smoke_flow.py](../scripts/smoke_flow.py) is the one automated run
that exists, and it needs the stack up.
