# Legacy migration archive

The former `0001_initial` through `0004_subscriptions_filters` chain was
removed from Alembic's active revision directory on 2026-07-29. Its first
revision created the schema from the application's live SQLAlchemy metadata,
which made a historical migration change whenever models changed.

The executable legacy files intentionally do not remain in this repository:
they must not be accidentally selected by Alembic, and the archived initial
revision contained the prohibited metadata-wide create/drop calls. The complete
historical source remains recoverable from Git before commit
`20260729_01_baseline`; the active schema is now the explicit,
reviewable `20260729_01_baseline` revision.

See [MIGRATIONS.md](../../MIGRATIONS.md) for the safe procedure to stamp an
already-current database onto the new baseline.
