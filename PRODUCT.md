# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Students use a Telegram bot to save CROUS accommodation searches and receive availability notifications. Operations staff use the protected administration panel to review subscriptions, purchases, monitoring activity, and administrator access.

## Product Purpose

The product monitors publicly available CROUS listings on behalf of Telegram users. It helps students react to availability changes and gives authorised staff a dependable view of the service's operational and payment data.

## Positioning

Search configuration, matching, notifications, payment activation, and operations reporting share one source of truth in the CROUS monitoring application rather than being separate tools.

## Operating Context

The bot runs continuously in the background. Administrators review data on desktop and mobile browsers, often while resolving a subscription or monitoring question. The system stores payment status and search state in PostgreSQL, receives payment confirmation from Stripe, and uses Telegram for end-user messages.

## Capabilities and Constraints

- Supported end-user locales are Arabic, English, French, Persian, Russian, Turkish, and Ukrainian.
- Searches use integer euro cents for price and square metres as the canonical area unit.
- Payment card data never reaches the application.
- The admin panel is protected by administrator roles: `admin` and `superadmin`.
- The admin prefix and public endpoints are configurable and must have safe defaults.
- The product must remain usable by keyboard and at widths down to 270px.

## Brand Commitments

The supplied xAI design system is binding for the administration surface: a near-black canvas, white type and hairline borders, compact 8px cards, and restrained animation. Revenue data uses a distinct green analytical accent as required by the admin specification.

## Evidence on Hand

- Existing ORM models, Alembic baseline, Telegram bot, Stripe integration, and localized Fluent catalogs are in this repository.
- The authoritative implementation prompt and API, frontend, and design blueprints were supplied with this task.
- No customer testimonials, branding assets, or external performance claims are available; the interface must not fabricate them.

## Product Principles

1. Preserve user search and subscription behavior while adding operations tooling.
2. Keep authorization and payment decisions on the server.
3. Make monitoring and transaction data explainable rather than decorative.
4. Treat localization, keyboard access, and narrow screens as first-class product requirements.

## Accessibility & Inclusion

The administration experience requires semantic controls, visible focus, keyboard-operable dialogs and data views, reduced-motion support, RTL-aware layouts, and responsive behavior down to 270px.
