# Dependency and supply-chain audit

Audit date: 2026-07-26

## Findings and remediation

- Direct dependencies used only wide lower bounds, so the same source tree could
  install different packages on different days. `uv.lock` now records the exact,
  hash-verified resolution for Python 3.12.
- Runtime and development dependencies are separated through the `dev` extra.
  Runtime images install with `--no-dev`.
- `python-dotenv` was declared directly but is already required by
  `pydantic-settings` and by `uvicorn[standard]`; the direct declaration was
  removed without changing functionality.
- Docker image tags were mutable. The Python, PostgreSQL, and Redis images are
  now pinned to tested patch releases.
- `pip-audit` reported no known vulnerabilities in the resolved third-party
  dependency set. The local project itself is correctly skipped because it is
  not published on PyPI.
- No deprecated or unmaintained direct Python package was identified.
- Stripe Checkout uses Stripe's HTTPS API through the existing `httpx` client;
  no card-processing SDK, browser automation, or additional payment dependency is
  introduced. Webhook verification uses Python standard-library HMAC and has
  fixture-based coverage for entitlement behavior.

## Resolved direct packages

| Area | Locked version | Compatibility decision |
| --- | --- | --- |
| Telegram | aiogram 3.30.0 | Kept within aiogram 3.x; existing APIs remain compatible. |
| HTTP API | FastAPI 0.140.0, Uvicorn 0.51.0 | Current FastAPI/Pydantic 2 stack; application import and tests pass. |
| Persistence | SQLAlchemy 2.0.51, asyncpg 0.31.0, Alembic 1.18.5 | Kept on SQLAlchemy 2.0 line; async migration path is verified. |
| Queue | ARQ 0.28.0, redis-py 5.3.1 | ARQ constrains redis-py below 6, so redis-py 8 is intentionally not selected. |
| HTTP/parsing | httpx 0.28.1 | CROUS results are consumed as JSON; no HTML parser is required. |
| Configuration/logging | pydantic-settings 2.14.2, structlog 26.1.0 | Current Pydantic 2-compatible releases. |
| Development | pytest 9.1.1, pytest-asyncio 1.4.0, Ruff 0.16.0, mypy 2.3.0 | The pytest/pytest-asyncio major updates were validated by the full test suite. |

## Intentional deferrals

- Redis server remains on the latest 7.x patch release (`7.4.9`). Redis 8 is a
  major server and licensing change, and redis-py 8 is outside ARQ's supported
  dependency range. Upgrade it as a separately planned datastore migration.
- PostgreSQL remains on major version 16 and is updated to patch 16.14. A
  PostgreSQL major upgrade needs a backup and data migration plan.
- Docker image CVE scanning requires a Docker Scout login in this environment,
  so it could not complete anonymously. The images were rebuilt from scratch
  and started successfully; run `docker login` followed by `docker scout cves`
  in CI or a logged-in production environment. Python package vulnerability
  auditing completed successfully.

## Repeatable checks

```bash
uv lock --locked
uv sync --locked --extra dev
uv run --locked --extra dev pytest
uv run --locked --extra dev ruff check .
uv run --locked --extra dev mypy app
uv run --locked --with pip-audit --extra dev pip-audit
docker compose build --no-cache
docker compose run --rm app alembic upgrade head
docker compose config --quiet
docker compose up -d app api admin_panel next_app proxy
docker compose exec proxy nginx -t
```
