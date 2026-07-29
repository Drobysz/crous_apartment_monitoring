# Dependency and supply-chain audit

Audit date: 2026-07-29

## Scope and outcome

This audit covers the Python project and lockfile, the Next.js application and
lockfile, container images, Compose configuration, and repository automation
configuration. All selected versions are stable releases available on the audit
date; prerelease, canary, RC, and nightly releases were excluded.

The upgrade completed without adding unused tooling. There are no GitHub Actions,
TypeScript, Tailwind CSS, ESLint, Prettier, pnpm, Yarn, or pre-commit
configuration files in this repository, so there are no dependencies or
migrations for those categories.

## Python and build tooling

| Package | Before | Resolved version | Decision |
| --- | --- | --- | --- |
| Python runtime | 3.12 only | 3.12–3.13 supported; container uses 3.13.14 | Expanded the supported range after rebuilding and testing with the new container runtime. |
| uv | 0.11.x | 0.12.0 | Updated the required build/lock-tool range and the pinned container image. |
| FastAPI | 0.140.0 | 0.140.13 | Stable patch upgrade; no route or Pydantic migration was required. |
| Uvicorn | 0.51.0 | 0.52.0 | Stable patch upgrade; existing `--host 0.0.0.0 --port 8000` commands remain valid. |
| aiogram | 3.30.0 | 3.30.0 | Latest stable direct release at audit time. |
| SQLAlchemy / asyncpg / Alembic | 2.0.51 / 0.31.0 / 1.18.5 | unchanged | Latest compatible stable releases; asynchronous migration coverage remains valid. |
| ARQ / redis-py | 0.28.0 / 5.3.1 | unchanged | ARQ constrains redis-py below 6; redis-py 8 is therefore intentionally excluded. |
| httpx / pydantic-settings / structlog | 0.28.1 / 2.14.2 / 26.1.0 | unchanged | Latest stable direct releases at audit time. |
| pytest / pytest-asyncio / Ruff / mypy / aiosqlite | 9.1.1 / 1.4.0 / 0.16.0 / 2.3.0 / 0.22.1 | unchanged | Latest stable compatible development releases at audit time. |

`uv.lock` was regenerated with uv 0.12.0. It now records FastAPI 0.140.13,
Uvicorn 0.52.0, and the required transitive `annotated-doc` patch update with
hashes for both supported Python minor versions.

## Next.js and Node.js

| Package or tool | Before | Resolved version | Decision |
| --- | --- | --- | --- |
| Next.js | 16.2.12 | 16.2.12 | Already the latest stable release. The app already uses the App Router and requires no Next 16 migration. |
| React / React DOM | 19.1.1 | 19.2.8 | Upgraded together to keep the renderer pair aligned. |
| PostCSS | 8.5.24 | 8.5.24 | Latest stable version, explicitly scoped as an npm override beneath Next.js. |
| Sharp | 0.35.3 | 0.35.3 | Latest stable version, explicitly scoped as an npm override beneath Next.js. |
| Node.js container | 22.18.0-alpine3.22 | 26.5.0-alpine3.24 | Upgraded to the current stable image and pinned by digest. |

The required override structure is intentionally nested under `next`:

```json
{
  "overrides": {
    "next": {
      "postcss": "8.5.24",
      "sharp": "0.35.3"
    }
  }
}
```

The frontend has no TypeScript, Tailwind CSS, ESLint, `eslint-config-next`, or
other frontend build-tool dependency. None was added solely for this audit.

## Container images

| Service | Before | Selected image | Compatibility decision |
| --- | --- | --- | --- |
| Python application services | Python 3.12.13 | Python 3.13.14 slim-trixie, digest pinned | Compatible with the expanded Python range. |
| uv build tool | 0.11.32 | 0.12.0, digest pinned | Matches the lockfile tool requirement. |
| Next.js service | Node 22.18.0 alpine3.22 | Node 26.5.0 alpine3.24, digest pinned | `npm ci` and production build are validated. |
| PostgreSQL | 16.14 alpine3.24 | 16.14 alpine3.24, digest pinned | PostgreSQL 18 is a major data-format migration and is deliberately deferred. |
| Redis | 7.4.9 alpine3.21 | 7.4.10 alpine3.21, digest pinned | Latest patch in the deployed Redis 7 line. Redis 8 is a separately planned server migration. |
| Internal proxy | floating `nginx:alpine` | nginx 1.30.4 alpine3.24, digest pinned | Removes the mutable tag while keeping the HTTP-only proxy configuration. |

## Security and compatibility checks

- `npm audit --omit=dev` reports no known production vulnerabilities.
- The Python vulnerability audit is run against the locked production and
  development resolution with `pip-audit`; the project itself is skipped because
  it is not a published PyPI distribution.
- No deprecated or unmaintained direct package was identified.
- Stripe continues to use the existing `httpx` integration; no card-processing
  SDK or additional payment dependency is introduced.
- The application uses no GitHub Actions or other repository CI automation to
  upgrade. Container digests make the selected runtime inputs reproducible.
- The frontend build context excludes local `node_modules` and `.next` output,
  so the Linux container keeps the `npm ci` dependency tree it installed rather
  than receiving host-platform artifacts.

## Intentional major-version deferrals

- PostgreSQL remains on 16.14. Moving an existing `postgres_data` volume to
  PostgreSQL 18 requires a backup, tested `pg_upgrade` or logical restore, and a
  rollback plan; changing the image alone would make the current data volume
  unusable.
- The Redis service remains on the 7.x line. Redis 8 requires an independent
  datastore compatibility review, and the queue library currently constrains the
  Python Redis client below version 6.

## Repeatable checks

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
