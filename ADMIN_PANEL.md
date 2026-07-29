# Administration panel

The protected panel is mounted at `/panel/`. It is served by the existing Next.js application and calls the same-origin API under `/crous_bot_api/admin`. Nginx keeps the Python API private inside the Compose network.

## Authentication and authorization

- Administrator usernames are normalized to lowercase Telegram-style `@username` values and use a case-insensitive unique key.
- Passwords are validated and hashed with bcrypt. The CLI never prints a password or hash.
- The browser receives a 15-minute signed, HttpOnly access cookie and a rotating, 30-day HttpOnly refresh cookie. Refresh tokens and CSRF tokens are stored only as hashes.
- State-changing API calls require matching same-origin `Origin` and `X-CSRF-Token` checks. Login attempts are rate-limited.
- The API resolves the active administrator and role from PostgreSQL on every protected request.
- Only superadmins can create or change administrators. An administrator cannot change their own role, and the last active superadmin cannot be deactivated or demoted.

Create the initial account after migrations:

```sh
python -m app.admin.cli create-superadmin --name "Operations lead" --username @gogona
```

Use `--password-stdin` only in deployment automation. Existing accounts are changed only with `--update-existing`.

## API and data handling

The API exposes server-side paginated, searchable endpoints for administrators, paid users, and transactions. Dashboard revenue uses only `paid`, non-test purchases. The dashboard’s active monitoring count is the number of currently enabled search configurations, not the number of cities.

Transaction detail responses intentionally omit card data, webhook signatures, and webhook payloads. Stripe Checkout and Payment Intent identifiers are treated as operational identifiers, never as credentials.

## Domain boundaries

```text
app/
  bot/                 primary student-facing Telegram bot
  notification_bot/    independent operational Telegram bot and webhook
  admin/               authentication, roles, reporting API, and CLI
  db/                  shared ORM metadata and database session
  searches/            search filters and listing matching
  payments/            Stripe checkout and payment activation
web_app/               localized administration panel
```

The existing ORM module remains the only Alembic metadata source. The notification bot has its own token, webhook secret, route, process, and handler router; it does not consume primary-bot updates.
