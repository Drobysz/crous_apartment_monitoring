# CROUS Logement Bot

Multilingual Telegram monitoring for publicly listed CROUS accommodation. The user interface supports English, Russian, Ukrainian, Turkish, Persian, French, and Arabic. It uses the live CROUS structured search endpoint, not authentication or protection bypasses. See [INVESTIGATION.md](INVESTIGATION.md) for the verified request mechanism and architecture.

The bot offers Free, one-time Trial, Season, and optional Lifetime access. Paid plans use Stripe Checkout; payment card data never reaches the bot. See [SUBSCRIPTIONS.md](SUBSCRIPTIONS.md) for product rules and [openapi.yaml](openapi.yaml) for webhook contracts.

## Requirements and configuration

Python 3.12 or 3.13, PostgreSQL 16, Redis 7, and a Telegram bot token are required. The project uses uv 0.12.x; the Docker images provide Python 3.13. Copy `.env.example` to `.env`, set `TELEGRAM_BOT_TOKEN`, and use a production PostgreSQL `DATABASE_URL` and Redis `REDIS_URL`. Secrets are never committed or logged.

### Subscription configuration

For Stripe Checkout, configure `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, and `PUBLIC_BASE_URL`. Checkout prices are always read from PostgreSQL (`subscription_plans.price_cents`) and submitted to Stripe as EUR `price_data`; Stripe Price IDs are not used. The success return page retrieves the Checkout Session directly from Stripe and activates access only when its verified `payment_status` is `paid`; the signed webhook remains an idempotent confirmation path.

The following product values are configurable without changing Telegram handlers:

| Setting | Default | Purpose |
| --- | --- | --- |
| `FREE_MONITORING_INTERVAL_SECONDS` | `3600` | Free monitoring cadence. |
| `PREMIUM_MONITORING_INTERVAL_SECONDS` | `120` | Trial, Season, and Lifetime cadence. |
| `TRIAL_DURATION_HOURS` | `12` | One-time Trial duration per Telegram account. |
| `SEASON_START_MONTH` / `SEASON_START_DAY` | `7` / `7` | Season opening date. |
| `SEASON_END_MONTH` / `SEASON_END_DAY` | `10` / `31` | Season closing date. |
| `ENABLE_LIFETIME_PLAN` | `true` | Makes the optional Lifetime plan available. |
| `TEST_MODE` | `false` | Enables the developer-only subscription reset button. |
| `DEVELOPER_TELEGRAM_IDS` | empty | Comma-separated Telegram IDs allowed to use the test reset. |
| `MAX_FILTER_PRICE_EUROS` | `10000` | Maximum accepted upper bound for a price filter. |
| `MAX_FILTER_SURFACE_M2` | `1000` | Maximum accepted upper bound for a surface filter. |

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

Set `RUN_MODE=webhook`, `PUBLIC_BASE_URL=https://bot.example.org`, and a long `WEBHOOK_SECRET`; then run the API and worker as distinct processes:

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
uv run arq app.workers.tasks.WorkerSettings
```

The API exposes `/healthz`, `/telegram/webhook`, `/stripe/webhook`, `/crous_bot_api/*`, `/panel/*`, `/web_app/*`, and payment return pages. Register the Stripe endpoint at `https://your-host/stripe/webhook` and subscribe to `checkout.session.completed`. Stripe must send its signing secret through the configured `STRIPE_WEBHOOK_SECRET`; invalid signatures and stale signed payloads are rejected.

Do not expose the Stripe endpoint through a client application. The success redirect contains only a Checkout Session ID; the backend retrieves that session from Stripe, validates the server-generated metadata and database price, and activates the entitlement transactionally only when Stripe reports it as paid. The signed webhook performs the same idempotent validation as a reliable fallback. Both return pages direct the user back to Telegram and notify the related chat.

## Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

The Compose `migrate` service applies the schema before the app, API, administration, and worker services start. For the explicit baseline and the safe adoption procedure for a pre-existing database, see [MIGRATIONS.md](MIGRATIONS.md).

The Compose stack includes an internal HTTP-only Nginx router. It publishes `NGINX_EXTERNAL_PORT` (default `8080`) and forwards webhooks, payments, API, administration, and web-app paths to their internal services. It has no TLS, certificate, redirect, or domain configuration. Point the existing Nginx Proxy Manager at `http://SERVER_IP:8080`; it remains solely responsible for HTTPS and certificates.

The app, API, and administration services listen only on their Compose-network ports (`8000`); the Next.js service listens on `3000`. In `RUN_MODE=webhook`, the app starts Uvicorn automatically on `0.0.0.0:8000`.

| External path | Internal target | Forwarded path |
| --- | --- | --- |
| `/telegram/webhook`, `/stripe/webhook`, `/payments/*`, `/` | `app:8000` | unchanged |
| `/crous_bot_api/*` | `api:8000` | prefix removed |
| `/panel/*` | `admin_panel:8000` | prefix removed |
| `/web_app/*` | `next_app:3000` | prefix removed |

## Verification

Tests are entirely fixture-based and make no live CROUS calls:

```bash
uv run --extra dev pytest
uv run --extra dev ruff check .
uv run --extra dev mypy app
uv run --with pip-audit --extra dev pip-audit
docker compose config --quiet
docker compose up -d app api admin_panel next_app proxy
docker compose exec proxy nginx -t
(cd web_app && npm ci && npm audit --omit=dev && npm run build)
```

## Operations notes

- Searches are queued independently. The worker runs every minute and enqueues a search only when its effective entitlement interval is due: 60 minutes for Free and two minutes for premium plans by default.
- Disabling monitoring sets the selected search inactive without deleting its location, filters, or listing history.
- Price, surface, and accommodation-format filters are applied locally to both monitored notifications and “Current apartments.” Listings with missing data are excluded only when a configured filter requires that comparison.
- The worker expires Trial and Season entitlements, falls users back to Free, and sends a single expiration notice.
- CROUS tool IDs are discovered through `/api/global/context`, because campaigns change by year.
- Cards use the listing's primary image when available; a secure, bounded download fallback is used if Telegram cannot fetch it.

## Administration and operations bots

After applying migrations, create the first administration account interactively:

```bash
uv run python -m app.admin.cli create-superadmin --name "Operations lead" --username @gogona
```

For deployment automation, pass the password over standard input and explicitly opt into an existing-account update:

```bash
printf '%s\n' "$ADMIN_PASSWORD" | uv run python -m app.admin.cli create-superadmin \
  --name "Operations lead" --username @gogona --password-stdin --update-existing
```

Set `ADMIN_SESSION_SECRET` to a long random value before enabling `/panel/`. The panel uses server-owned, rotating HttpOnly sessions; it exposes no raw bearer token to browser code. See [ADMIN_PANEL.md](ADMIN_PANEL.md) for its API, roles, and deployment boundaries, [FILTER_AUDIT.md](FILTER_AUDIT.md) for filter semantics, and [DESIGN_ACCESSIBILITY_REPORT.md](DESIGN_ACCESSIBILITY_REPORT.md) for the responsive and keyboard design review.

`NOTIFICATION_BOT_TOKEN` and `NOTIFICATION_WEBHOOK_SECRET` configure the independent operational notification bot. An active administrator must start it from their private Telegram chat; the bot matches that Telegram username to the administrator account before registering the chat for notifications. Its public webhook path is `/notification_bot/webhook`; it runs separately from the student-facing Telegram bot.
