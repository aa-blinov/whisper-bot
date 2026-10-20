# Documentation

The documents for whisper-bot.

| Document | What it covers |
| --- | --- |
| [architecture.md](architecture.md) | How the bot is put together: the modules, the data flow and the boundaries. |
| [../README.md](../README.md) | The front door: what the bot does and how to run it. |
| [../AGENTS.md](../AGENTS.md) | The commands, the traps and the rails for a session that opens the repository. |
| [../PRODUCT.md](../PRODUCT.md) | The product truth the code is measured against. |
| [../DESIGN.md](../DESIGN.md) | The screen the person sees: the keyboard, the messages and the statistics. |

## Reading order

New here: [../README.md](../README.md), then [architecture.md](architecture.md).

Changing the bot: [architecture.md](architecture.md), then
[../AGENTS.md](../AGENTS.md) for the traps. The interface is described in
[../DESIGN.md](../DESIGN.md), and the strings a person reads are in Russian
in both the code and the document.

## What is not here

There is no guide for the deployment beyond the `docker-compose.yml` in the
root, and there is no test guide: the repository has no test command and
`tests/test_bot.py` is empty.
