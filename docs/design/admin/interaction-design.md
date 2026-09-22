# PDF Master operations design • v1

The administration application belongs only to `document-platform`. It shares the customer's warm ivory, forest and sage palette, with denser tables and a restrained editorial heading. Runtime figures always come from database facts. A development account is explicitly identified and excluded from production reports by default.

## Information architecture and task flows

Overview → filtered user / job lists → metadata detail. Acquisition, engagement and feature reports reuse one filter object and metric definition version. Support → open ticket → resolved status with mandatory reason → immutable audit event. System → queue/storage/retention diagnostics. Plans → staging limits and disabled commercial publication. Financial views disclose unavailable integration until the payment ledger exists.

Staff login → password → TOTP (required outside local development) → separate, eight-hour staff session. Staff groups gate both HTML and JSON/CSV routes. Analyst cannot inspect identifiable user records, download files, or mutate support state. Staff never receive private document download URLs.

## Wireframes

1440 px: 232 px left sidebar | header (breadcrumb, locale, staff identity) | title + description | shared filter panel | four KPI cards | 2:1 chart/detail grid | recent task table. Chart has an equivalent data table. Staff table rows are at least 44 px tall. Main content max width 1440 px.

390 px: compact top brand/header | horizontal navigation disclosure | stacked filters | two-column metrics | stacked chart and list | horizontally scrollable named table region. No fixed overlay covering actions. Dense financial operations remain desktop-oriented.

## Component states

- Metric: measured number (including zero), not yet observable (insufficient cohort age), unavailable (no authoritative integration), failed (query failure; never fabricated zero).
- Dataset: loading is a server navigation; true empty has clear explanatory text and active filter context.
- Filters: URL-persisted inclusive local date start / exclusive local date end, timezone, locale, channel, environment. Date conversion occurs once and applies to all rows, totals and exports.
- Tables: full accessible column headers, links for drilldown, no content or filenames in general operational lists.
- Support action: role permission, CSRF protection, audit reason, clear success/error message.
- Focus: visible 3 px sage ring, semantic landmarks, skip link, 44 px controls; reduced-motion preference.
- Locale: English, Uzbek Latin, Russian with wrapping labels and no fixed text height. Locale selection remains independent of reporting timezone.

## Visual QA targets

1440×1000 overview, 390×844 overview, 1024 px users/support; all three locales. Verify no body overflow, Cyrillic and Uzbek apostrophes, zero versus unavailable labels, export reconciles to displayed rows, keyboard tab order. Real Telegram device QA remains a deployment gate, not a local screenshot claim.
