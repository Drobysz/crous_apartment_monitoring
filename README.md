# CROUS Logement Bot

Multilingual (Russian, French, Arabic) Telegram monitoring for publicly listed CROUS accommodation. It uses the live CROUS structured search endpoint, not authentication or protection bypasses. See [INVESTIGATION.md](INVESTIGATION.md) for the verified request mechanism and architecture.

## Requirements and configuration

Python 3.12, PostgreSQL 16, Redis 7, and a Telegram bot token are required. Copy `.env.example` to `.env`, set `TELEGRAM_BOT_TOKEN`, and use a production PostgreSQL `DATABASE_URL` and Redis `REDIS_URL`. Secrets are never committed or logged.

## Local setup

```bash
uv sync --extra dev
uv run alembic upgrade head
uv run python -m app.bot.runner
```

The polling process uses Redis-backed aiogram FSM. Start the shared monitoring worker separately:

```bash
uv run arq app.workers.tasks.WorkerSettings
```

## Webhook production mode

Set `RUN_MODE=webhook`, `WEBHOOK_BASE_URL=https://bot.example.org`, and a long `WEBHOOK_SECRET`; then run the API and worker as distinct processes:

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
uv run arq app.workers.tasks.WorkerSettings
```

The API exposes `/healthz` and validates Telegram’s webhook secret header.

## Docker Compose

```bash
cp .env.example .env
docker compose up --build
docker compose exec app alembic upgrade head
```

## Verification

Tests are entirely fixture-based and make no live CROUS calls:

```bash
uv run --extra dev pytest
uv run --extra dev ruff check .
uv run --extra dev mypy app
uv run --with pip-audit --extra dev pip-audit
```

## Operations notes

- Search zones are grouped by identical validated bounds in the shared worker; this prevents one CROUS request per user.
- The first successful snapshot is a baseline. Only later additions/reappearances notify users.
- CROUS tool IDs are discovered through `/api/global/context`, because campaigns change by year.
- CROUS dynamic content stays in its original form; only interface labels are localized.
