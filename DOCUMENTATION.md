# Project documentation

This document consolidates the operational, product, migration, security,
filter, design, and dependency notes for the CROUS Logement Bot. The concise
entry points remain [README.md](README.md) for setup and
[INVESTIGATION.md](INVESTIGATION.md) for the verified CROUS integration.

## Product and subscriptions

Students use the multilingual Telegram bot to save CROUS accommodation searches
and receive availability notifications. Operations staff use the protected admin
panel to review subscriptions, purchases, monitoring activity, and administrator
access. Supported student locales are Arabic, English, French, Persian, Russian,
Turkish, and Ukrainian.

| Code | Access | Default interval | Validity |
| --- | --- | --- | --- |
| `free` | Current listings and basic notifications | 60 minutes | Unlimited |
| `trial` | Premium features, once per Telegram account | 2 minutes | 12 hours |
| `season` | Premium features | 2 minutes | Configured CROUS season |
| `lifetime` | Premium features; optional | 2 minutes | Unlimited |

Premium features are `check_now`, `advanced_filters`, and priority-monitoring
eligibility. Localized labels are presentation-only; these codes are the stable
business identifiers.

The default season runs from 7 July through 31 October, configured by numeric
month and day environment values. Purchases before or during that period receive
the current year's season; purchases after it receive the next year's season.
Entitlement timestamps are timezone-aware and remain in the purchase history.

Stripe Checkout is the only card-collection surface. Checkout prices come from
`subscription_plans.price_cents` in PostgreSQL and are submitted as EUR
`price_data`; Stripe Price IDs are not used. A paid success return and the signed
`checkout.session.completed` webhook share one transactional idempotency gate, so
retries cannot duplicate a purchase or extend access twice. Card data, webhook
signatures, and webhook payloads are never exposed in the administration API.

## Administration and notification bot

The protected panel is mounted at `/panel/`. It is served by the Next.js app and
uses the same-origin API under `/crous_bot_api/admin`; Nginx keeps the Python API
private inside the Compose network.

- Administrator usernames are normalized to lowercase Telegram handles in the
  `@username` form and have a case-insensitive unique key.
- Passwords are bcrypt-hashed. Browser access uses a 15-minute signed, HttpOnly
  cookie and a rotating 30-day HttpOnly refresh cookie. Refresh and CSRF values
  are stored only as hashes.
- State-changing API calls require same-origin and CSRF validation; login is
  rate-limited. The active administrator and role are resolved from PostgreSQL
  for every protected request.
- Only superadmins can change administrators. An administrator cannot alter
  their own role, and the final active superadmin cannot be deactivated or
  demoted.

Create the first account after migrations:

```sh
python -m app.admin.cli create-superadmin --name "Operations lead" --username @gogona
```

The independent notification bot has its own token, webhook secret, route,
process, and handler router. In a private chat, `/start` canonicalizes the
Telegram username to `@username` (including when Telegram's update JSON omits
the prefix), then matches it to an active administrator. It replies in Russian
whether operational notifications will be sent. Only registered chats for active
administrator usernames receive operational notifications.

The panel's list endpoints paginate and search server-side. Dashboard revenue
includes only paid, non-test purchases; its active-monitoring count is the number
of enabled search configurations rather than the number of cities.

## Monitoring filters

- Price is stored in integer euro cents; surface is stored in square metres.
- Accommodation format is stored as `individual` or `colocation`. A migration
  normalizes old `individuel` records, while matching continues to support them.
- An omitted saved field means its restriction is inactive. Bounds are inclusive.
- Price input uses `Decimal`, accepts ranges or one-sided `≥` / `≤` bounds, and
  rejects negative amounts, inverted ranges, excessive precision, invalid syntax,
  and configured-limit violations with stable localization codes.
- Surface supports independent bounds plus comma or dot decimal separators.
- Resetting filters requires a localized confirmation and never clears them on
  cancellation.

Tests cover exact boundaries, one-sided ranges, no-bound behaviour, decimal
separators, invalid input, legacy format compatibility, and representative CROUS
listing matches.

## Database migrations

The active Alembic history is a linear four-step chain:

```text
20260729_01_base -> 20260729_02_admin -> 20260729_03_filters -> 20260729_04_notify
```

The base revision creates the historical starting schema and Season/Lifetime
plans. Later revisions add the administration domain, Telegram username/filter
code changes, and verified notification chats. Revision IDs are ASCII,
deterministic, and no longer than 32 characters. Historical revisions are
immutable snapshots: they do not import ORM models or invoke metadata-wide table
creation or deletion.

```bash
docker compose run --rm migrate
docker compose run --rm app alembic current
docker compose run --rm app alembic heads
docker compose run --rm app alembic history --verbose
```

The `migrate` Compose service is a one-shot job; dependent services wait for it
and must not create tables at application startup.

### Existing databases from the legacy history

Do not run `upgrade` against a database whose `alembic_version` still contains a
legacy `0001_*` through `0004_*` revision. First take and verify a PostgreSQL
backup, deploy the release whose schema already matches the baseline, and review
an equivalent staging copy. Only after that review confirms the schema is
current, replace the marker without altering data:

```bash
docker compose run --rm --no-deps migrate \
  alembic stamp --purge 20260729_04_notify
```

`--purge` is required because legacy identifiers are not in the active script
directory. Never run `alembic downgrade base` on production: the baseline
downgrade is deliberately destructive and only for disposable integration
databases.

Run the migration round-trip suite only against a dedicated disposable database:

```bash
MIGRATION_TEST_DATABASE_URL=postgresql+asyncpg://crous:crous@127.0.0.1:55432/crous_test \
uv run --extra dev pytest -m integration
```

It validates every upgrade and downgrade step, an idempotent final upgrade, and
`alembic check`. The old executable migration chain is intentionally absent from
the repository so Alembic cannot select it; its history remains available in Git
before the `20260729_01_base` commit.

## Administration design and accessibility

The panel follows the supplied xAI system: system appearance by default with
explicit Auto, Light, and Dark options; near-black dark canvas; compact surfaces;
hairline borders; restrained motion; and a green analytical revenue accent.
There are no fabricated metrics, decorative charts, gradients, or ambient
animation.

Keyboard and responsive requirements include a skip link, semantic navigation,
visible focus, semantic and focus-managed dialogs, reduced-motion handling,
keyboard-operable chart points, intentional table scrolling, RTL-aware logical
CSS, and support down to 270px. Review production data at 270, 320, 360, 375,
390, 768, 1024, 1280, and 1440px.

## Dependency and supply-chain baseline

Audit date: 29 July 2026. The supported runtime range is Python 3.12–3.13; the
container uses Python 3.13.14. The project uses uv 0.12.0, FastAPI 0.140.13,
Uvicorn 0.52.0, aiogram 3.30.0, Next.js 16.2.12, React 19.2.8, PostgreSQL
16.14, and Redis 7.4.10. Container images are digest-pinned where selected.

PostgreSQL 18 and Redis 8 are deliberately deferred: each needs a separate data
compatibility and rollback plan. The frontend deliberately has no TypeScript,
Tailwind, ESLint, Prettier, pnpm, Yarn, or pre-commit configuration added solely
for dependency maintenance.

Repeatable checks:

```bash
uv sync --locked --extra dev
uv run --locked --extra dev pytest
uv run --locked --extra dev ruff check .
uv run --locked --extra dev mypy app
uv run --locked --with pip-audit --extra dev pip-audit
docker compose build --pull app next_app
docker compose config --quiet
docker compose up -d app api admin_panel next_app proxy
docker compose exec proxy nginx -t
(cd web_app && npm ci && npm audit --omit=dev && npm run build)
```
