# Database migrations

## Active history

`20260729_01_baseline` is the sole Alembic baseline. It creates every table,
foreign key, unique constraint, and index explicitly with Alembic operations.
It also seeds the active Season (EUR 10.00) and Lifetime (EUR 24.00) plans.
The `searches.last_changed_at` column is defined once, in that baseline.

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
4. Replace only the Alembic version marker, without changing tables or data:

   ```bash
   docker compose run --rm --no-deps migrate \
     alembic stamp --purge 20260729_01_baseline
   ```

5. Start the stack normally. Future migrations will extend
   `20260729_01_baseline`.

`--purge` is essential because the legacy revision identifiers no longer exist
in the active script directory. Never use `alembic downgrade base` against a
production database: the baseline downgrade is deliberately destructive and is
for disposable integration databases only.

## Integration check

The migration round-trip test needs a dedicated, disposable PostgreSQL database:

```bash
MIGRATION_TEST_DATABASE_URL=postgresql+asyncpg://crous:crous@127.0.0.1:55432/crous_test \
uv run --extra dev pytest -m integration
```

It validates `upgrade → downgrade → upgrade`, including the one-and-only
`searches.last_changed_at` column and subscription-plan seed records. It never
uses `DATABASE_URL`, so the application database cannot be selected by mistake.
