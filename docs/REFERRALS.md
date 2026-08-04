# Referrals, commissions, payouts, and promotional digests

Referral links use first-touch attribution: `/start ref_<referral_code>` records the first valid active code for a user and never overwrites it. Deactivating a referral stops new attribution while preserving history.

The application records a commission only after a verified Stripe `checkout.session.completed` payment. The current commission base is the captured EUR subscription amount before provider fees; taxes are included when they are included in the amount recorded by Stripe. Commission rows store their historical rate in basis points and use integer EUR cents, not floats. Administrator lifetime, complimentary, failed, test, and verified self-referral payments create no commission.

Refunds and chargebacks append a reversal entry instead of deleting the original commission. A refund after a manual payout becomes a negative future-earnings adjustment; the application never debits a creator's external account.

Balances are derived from the ledger: earned commissions minus reversals, active payout allocations, and paid allocations. A withdrawal is available from EUR 5.00. Requests reserve exact commission amounts transactionally and remain `requested` until an authorized administrator reviews them. The first release uses the `manual` provider only: an administrator records the external transfer reference and marks an approved request paid. Reconcile external transfers against payout IDs and allocated commission rows before accounting or tax reporting. Obtain local accounting and tax advice before operating the programme.

Creators begin with the separate referral bot. It binds a verified numeric Telegram ID after the configured username matches, then issues a short-lived, single-use HTTPS statistics link. The browser exchanges that link token for a scoped owner session; creator endpoints can access only the bound referral.

Unsubscribed promotional housing messages are limited to one deterministic UTC interval per user. Users can opt out with `Stop these messages`; support can re-enable the preference in the database. The scheduler uses completed persisted listing data only and does not create a timer per user.

Required configuration is documented in `.env.example`. Enable the optional `referral` compose profile to run the owner bot. `REFERRAL_STATS_BASE_URL` must be HTTPS outside test mode. Automated payout providers are intentionally out of scope; provider-neutral payout and allocation records are retained for a future integration.
