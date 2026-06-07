# Python Bot

Public-safe Python bot base built on NoneBot2 + OneBot V11.

This repository keeps only reusable bot infrastructure and neutral features. It does not include role prompts, private memory, chat history, runtime databases, secrets, logs, or research materials.

## Features

- `ping` / `about` / `help`
- sign-in
- points
- utility commands
- fun commands
- Bilibili video parsing
- local admin web
- optional LLM adapter
- public-safe `bot_brain` pipeline

## Privacy Boundary

This repository does not ship:

- role prompts or profile sheets
- private memory or user profiles
- chat logs or exported runtime data
- local databases, caches, browser session files, or downloads
- secrets, API tokens, or account credentials

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
```

## Configure

```bash
cp .env.example .env
```

OneBot V11 WebSocket example:

```text
ws://127.0.0.1:8080/onebot/v11/ws
```

All keys in `.env.example` are placeholders only.

## Run

```bash
python bot.py
```

## Test

```bash
unset PYTHONPATH
python scripts/check_syntax.py
python -m compileall src
python -m pytest -q
```

## Bilibili Notes

- supports normal video links and small-app/card text extraction
- pre-resolves `b23.tv` short links
- inspects dynamic links and continues only when a video URL can be recovered
- sends cover plus summary first, then uploads the video as a file
- uses a unified file-upload path instead of native video messages
- non-video dynamics stay silent by default

## `bot_brain`

`src/chatbot/bot_brain/` is a neutral processing pipeline for reusable bot logic:

- observation
- context
- retrieval
- planner
- generator
- critic
- fallback
- local store

It does not include role prompts, private memory, real user profiles, or chat transcripts.

## Safety Notes

Do not commit:

- `.env`
- `data/`
- `logs/`
- `cache/`
- downloaded media
- browser session files
- local databases
- real chat history
