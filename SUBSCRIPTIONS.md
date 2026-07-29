# CROUS Bot subscriptions

## Plans

| Code | Access | Default interval | Validity |
| --- | --- | --- | --- |
| `free` | Current listings and basic notifications | 60 minutes | Unlimited |
| `trial` | Premium features, once per Telegram account | 2 minutes | 12 hours |
| `season` | Premium features | 2 minutes | Configured CROUS season |
| `lifetime` | Premium features; optional | 2 minutes | Unlimited |

Premium features are `check_now`, `advanced_filters`, and priority-monitoring eligibility. The UI always uses localized names; the stable codes above are the only business identifiers.

## Season calculation

The default season is 7 July through 31 October, configured with numeric month/day environment values. A purchase before or during the season is assigned to that year's window. A purchase after the season is assigned to the following year's window. Both entitlement timestamps are timezone-aware and are retained in the history table.

## Payment safety and idempotency

Stripe Checkout is the sole card-collection surface. The bot creates a Checkout Session with `price_data`: the EUR amount is read from the `subscription_plans.price_cents` PostgreSQL column for every checkout. No Stripe Price IDs are configured. Metadata includes the internal user ID, Telegram user ID, plan ID, and plan code. The success/cancellation URLs only return the customer to a web page.

`POST /stripe/webhook` verifies Stripe's timestamped HMAC signature. It processes only paid `checkout.session.completed` events, verifies that the metadata matches an existing user and configured plan, then writes the purchase and entitlement in one transaction. Unique Checkout Session and Stripe event IDs make replayed delivery harmless. See [openapi.yaml](openapi.yaml) for the full endpoint contract.

## Operations

The ARQ scheduler evaluates every active search each minute and schedules it only after the effective plan interval has elapsed. Expired timed entitlements fall back to Free automatically and receive at most one expiration notification. Monitoring can be disabled independently of subscription status; it preserves the user's location and filters.
