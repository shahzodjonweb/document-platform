# Telegram document bot — complete implementation handoff

Prepared 2026-09-22.

This package defines a Telegram bot, customer web app/Mini App, backend and admin panel. It is ready to give to an AI coding agent. It is a planning deliverable; the software has not yet been implemented.

## Fixed structure

| Repository | Contents |
|---|---|
| document-web | Customer website, customer application, Telegram Mini App, frontend localization and generated public API client |
| document-platform | Telegram bot, backend API, workers, billing, database, admin UI, analytics, deployment configuration |

Languages: Uzbek Latin, English, Russian. Plans: Free, Plus, Premium.

Proposed stack: Nuxt 4/Vue 3/TypeScript for the customer app; Python/Django/PostgreSQL/Celery for the platform; custom Django admin dashboards in repository 2.

## Files and how to use them

| File | Purpose |
|---|---|
| AGENT_START_HERE.md | Copyable implementation prompt, agent roles and first working checkpoint |
| IMPLEMENTATION_PLAN.md | Full architecture, database/API design, policies, billing, security, admin metrics and release acceptance |
| UI_UX_SPEC.md | Dedicated UI/UX-agent specification: routes, flows, tokens, components, screen states and multilingual design |
| DELIVERY_BACKLOG.md | 48 ordered tickets, dependencies and concrete acceptance conditions |
| delivery_backlog.json | Machine-readable tickets mapping every feature ID to exactly one owner ticket |
| feature_catalog.csv | Complete 128-feature category and Free/Plus/Premium matrix |
| feature_catalog.json | Same catalog with stable IDs, release gates, labels and usage meters |
| plan_seed.json | Editable staging quotas/tariffs; paid production prices intentionally unset |

Give the coding agent the whole folder, then use AGENT_START_HERE.md. Read the master plan for policy decisions and the CSV for a quick plan comparison.

## Delivery order

1. R0: foundations, UI/UX design, three-language shells, identity, ledger and admin baseline.
2. R1A: useful Free PDF tools across bot, browser and Mini App.
3. R1B: OCR/editable conversions, batches, subscriptions, complete paid-user analytics and a validated paid launch.
4. R2A: AI-generated multilingual PDFs and editable PPTX, templates, revisions and credit packs.
5. R2B: student, school and teacher capabilities with safe sharing and reviewed education outputs.
6. R3: visual PDF editing, actual existing-content changes, true redaction and form workflows.

Compression, images-to-PDF, merging, splitting and Word-to-PDF are the initial acquisition priorities. This prioritization is a product hypothesis, not a claim about measured usage. The admin reports will measure which tools people actually use and pay for.

## Admin coverage

The plan includes new-user trends, registration sources/locales/channels, activation and retention cohorts; current and first-time paid users; plan distribution, renewals, cancellation intent, expiry, churn and reactivation; Stars inflows/refunds and subscription run-rate; feature adoption, usage, provider cost and processing quality; support, referrals, worker health and cleanup.

Every KPI has a defined population/time window, consistent drilldowns/exports, test-data exclusions, role permissions and audit requirements. Paying once, having an active subscription and renewing are deliberately separate metrics.

## Commercial and implementation gates

The 128-feature catalog describes the full roadmap. The pricing page must sell only enabled, completed features. All feature flags start disabled in this handoff.

Staging quotas and credit tariffs are starting examples for engineering and cost tests. Production Plus/Premium prices are null, and live checkout is disabled. Set validated prices through versioned admin configuration before selling subscriptions.

Telegram digital purchases use Stars in the initial design. An ordinary browser uses the same Telegram checkout and canonical account. Processing limits must match the actual deployed Telegram transport; larger uploads have an authenticated web fallback when needed.

The biggest technical uncertainties are editable PDF-to-Word fidelity, multilingual content quality and genuine existing-content PDF editing/redaction. They have explicit engine/provider/license spikes and release gates instead of unsupported promises.

## Package validation

The preparation check verifies that all 128 catalog IDs are unique, all three plans/locales are present, every feature maps once to a ticket in its correct release, dependencies form a valid ordered graph, and production billing remains disabled. These checks validate the planning package, not unbuilt application behavior.
