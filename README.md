# Python Bot

A clean Python chatbot template built with NoneBot2, OneBot V11, NapCat QQ, FastAPI, and WebSocket.

This repository is intended as a public starter project: it contains only generic code, example configuration, and reusable plugins. Do not commit real tokens, local runtime data, chat logs, or NapCat private configuration.

## Tech Stack

- Python
- NoneBot2
- OneBot V11
- NapCat QQ
- FastAPI
- WebSocket
- yt-dlp / ffmpeg for optional Bilibili video handling

## Runtime Chain

```text
QQ Client / NapCat
-> OneBot V11 WebSocket Client
-> NoneBot2 server
-> plugins
```

The Python process does not log in to QQ. NapCat or another OneBot V11 client logs in to QQ and connects back to the NoneBot2 server.

## Installation

```bash
cd Python_Bot
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e ".[onebot,dev]"
cp .env.example .env
```

Edit `.env` and fill only your own local configuration. Do not commit `.env`.

## Start

```bash
python bot.py
```

The default server listens on:

```text
http://127.0.0.1:8080
```

## NapCat Configuration

In NapCat or another OneBot V11 client, add a reverse WebSocket client endpoint:

```text
ws://127.0.0.1:8080/onebot/v11/ws
```

If you configure an access token in NapCat, set the same token in `.env` with `ONEBOT_V11_ACCESS_TOKEN`. Keep it private.

Use a placeholder in docs and examples, such as `YOUR_QQ_ID` or `123456789`; do not hard-code a real QQ number.

## Web Admin

Open the local admin page after startup:

```text
http://127.0.0.1:8080/admin
```

For non-local deployments, set a strong value for:

```env
CHATBOT_ADMIN_TOKEN=
```

## Included Plugins

- `core`: ping, help, about, startup logging
- `utility`: echo, calculator, choose, dice, time
- `fun`: fortune and small random commands
- `admin`: local web admin APIs and status
- `bilibili`: optional Bilibili link parsing and mp4/file sending
- `sign`: daily sign-in example
- `points`: simple points ledger example

Private persona, memory, diary, custom prompt, and character-specific modules are intentionally not included in this public template.

## Commands

Core:

- `/ping`
- `/cbhelp`
- `/cbhelp all`
- `/about`
- `/status`

Utility:

- `/echo content`
- `/calc 1 + 2 * 3`
- `/choose A | B | C`
- `/roll 20`
- `/time Asia/Shanghai`

Fun:

- `/fortune`
- `/draw [topic]`
- `/8ball question`
- `/rate target`
- `/crazy name`

Bilibili:

- Send a Bilibili video URL in chat to parse it
- `/bili status`
- `/bili on`
- `/bili off`
- `/bili clean`

Sign and points:

- `/sign`
- `/sign info`
- `/sign rank`
- `/points`
- `/points rank`

## Bilibili Dependencies

The Bilibili plugin uses `yt-dlp`. For best video compatibility, install `ffmpeg` on your system.

macOS example:

```bash
brew install ffmpeg
```

Temporary Bilibili downloads use `downloads/bilibili` by default and are ignored by git.

## Develop a Plugin

Create a new package under `src/plugins`, for example `src/plugins/weather/__init__.py`:

```python
from nonebot import on_command
from nonebot.params import CommandArg

weather = on_command("weather", priority=5, block=True)

@weather.handle()
async def handle_weather(args=CommandArg()):
    city = args.extract_plain_text().strip() or "Shanghai"
    await weather.finish(f"Weather plugin placeholder for {city}.")
```

NoneBot loads plugin packages from `src/plugins` through `pyproject.toml`.

## Tests

```bash
python scripts/check_syntax.py
python -m compileall src
pytest
```

## Security Notes

Never commit:

- `.env`
- API keys or tokens
- real QQ numbers or account data
- NapCat local configuration
- `data/` runtime files
- chat logs or memory files
- cache, temp, downloads, video files
- `.venv/` or other virtual environments

Before pushing to GitHub, run a sensitive-content scan and inspect staged files. For example, search for private keys, local paths, real account IDs, and generated data before committing.

```bash
git status --short
git diff --cached --name-only
```

If a key was ever exposed, rotate it before publishing.
