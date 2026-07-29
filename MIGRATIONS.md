# Database migrations

## Active history

The active history is a linear, explicit four-step chain:

```text
20260729_01_base -> 20260729_02_admin -> 20260729_03_filters -> 20260729_04_notify
```

`20260729_01_base` creates the historical starting schema and seeds the active
Season (EUR 10.00) and Lifetime (EUR 24.00) plans. The following revisions add
the administration domain, Telegram username/filter-code update, and verified
notification chats respectively. `searches.last_changed_at` is defined exactly
once, in the base revision.

Revision IDs are ASCII, deterministic, and at most 32 characters because
Alembic stores them in `alembic_version.version_num VARCHAR(32)`. Revision
files are immutable historical snapshots: they must not import application ORM
models or call `Base.metadata.create_all()` / `drop_all()`.

No active migration creates PostgreSQL enum types. If a future migration adds
one, it must explicitly create it during upgrade and remove it during downgrade.

## Apply and inspect migrations

```bash
docker compose run --rm migrate
docker compose run --rm app alembic current
docker compose run --rm app alembic heads
docker compose run --rm app alembic history --verbose
```

The Compose `migrate` service is a one-shot job. Database-dependent services
wait for it to complete successfully and must never create tables at startup.

For a new database, the Compose `migrate` service runs `alembic upgrade head`
after PostgreSQL becomes healthy. Application services wait until it completes
successfully.

## Existing databases created by the old history

The old revisions are deliberately not a parent of the new baseline. Do not run
`upgrade` directly against a database whose `alembic_version` still contains an
old `0001_*` through `0004_*` revision.

1. Take and verify a PostgreSQL backup.
2. Deploy the application release whose schema already includes subscriptions,
   display snapshots, filters, and `searches.last_changed_at`.
3. Review that database against the baseline in a staging copy.
4. Replace only the Alembic version marker, without changing tables or data.
   This is safe only after the staging review confirms that the database already
   has the full schema represented by the current head:

   ```bash
   docker compose run --rm --no-deps migrate \
     alembic stamp --purge 20260729_04_notify
   ```

5. Start the stack normally. Future migrations will extend
   `20260729_04_notify`.

`--purge` is essential because the legacy revision identifiers no longer exist
in the active script directory. Never use `alembic downgrade base` against a
production database: the baseline downgrade is deliberately destructive and is
for disposable integration databases only.

## Disposable integration check

The migration round-trip test needs a dedicated, disposable PostgreSQL database:

```bash
MIGRATION_TEST_DATABASE_URL=postgresql+asyncpg://crous:crous@127.0.0.1:55432/crous_test \
uv run --extra dev pytest -m integration
```

It validates every upgrade and downgrade step, `upgrade → downgrade → upgrade`,
an idempotent final upgrade, and `alembic check`, including the one-and-only
`searches.last_changed_at` column and subscription-plan seed records. It never
uses `DATABASE_URL`, so the application database cannot be selected by mistake.

## Clean local database

Only run this against a disposable local Compose database. The following command
deletes the local PostgreSQL volume and all of its data:

```bash
docker compose down -v
docker compose up -d
```
