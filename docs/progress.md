# PDF Master implementation progress

Updated 2026-09-23. The workspace has two independent source repositories, a running customer web/Mini App, Django API, Telegram bot and separate staff panel. Original documents and ticket statuses are preserved unchanged in `docs/product/`. They are product requirements, not permission to deploy or activate payments. The user's current instruction is to demonstrate locally before any Git push.

## Working local journeys

1. Private upload → server quote → reservation → actual PDF/OCR/Office/editor output → authorized download and usage receipt. Ineffective compression is free; failed tasks release reservations.
2. Sandbox plan purchase → real test subscription/grants → premium editor/batches → cancel or resume sandbox renewal without revoking current access. Sandbox facts are ignored in production and excluded from production reports.
3. Local bot `/start`/`/tools`/`/usage`, uploads, controls, task execution and actual artifact delivery through real aiogram handlers with local transport. `/create`, `/study`, `/school`, `/teach`, `/editor` connect to the corresponding web workspace.
4. Source/content → editable outline → real Unicode PDF or native editable PPTX. Local authoring requires supplied content and never pretends to call AI. Optional live structured provider calls require a configured model/key and confirmed quote.
5. Teacher worksheets and separate keys → expiring learner-only share → revocation. Saved projects require explicit 90-day consent; practice results and weak topics persist. Adaptive generation uses only the owner's saved practice history.
6. Named lesson, exam, weekly practice, differentiated and A/B/C variant packs. Local authoring transforms supplied content; it does not invent subject facts or claim psychometric difficulty calibration. Provider mode validates exact material slots and bills bounded actual outputs.
7. Saved workflows with signed confirmation, snapshot inputs, exact-once child jobs and crash recovery; independent batches with per-child outcomes; reusable form templates and Premium batch filling.
8. Separate staff sign-in, encrypted integration configuration, local bot start/stop, role/TOTP enrollment, support conversations, audited grants/actions, revenue, activity/retention and safe filtered exports.

Bot credentials now belong in **Admin → Integrations**, not an environment file. Secrets are encrypted and never redisplayed. The local `.private/integration.key` must be preserved with the database. No real Telegram or AI credential was configured at the latest verification checkpoint; live transport/provider success is not claimed.

## Delivery status

| Area | Implemented | Remaining acceptance |
|---|---|---|
| R0 foundations | Repositories, locked runtimes, auth realms, contracts, shared policy, localized responsive interfaces, operations roles/analytics/support | PostgreSQL concurrency/restore, real-device identity, language and operational signoff |
| R1A files/bot | Real file operations, private uploads/previews, bounded parsers, durable jobs, encrypted passwords, polling/webhook/local bot, retention | Stable Office deployment, production filesystem/network containment, live Telegram/device testing |
| R1B advanced/commerce | OCR, editable text/table conversion, batches/workflows, subscriptions/packs/refunds/reconciliation, referrals, revenue reports | Live Stars configuration, measured economics, larger Telegram transport, production load tests |
| R2A generation | Encrypted drafts, source extraction, separately quoted AI outlines, structured provider, PDF/PPTX renderer, branding/templates, selected-section revision, supporting image adapter | Live model/image configuration and quality/cost benchmark |
| R2B education | Shared study/school/teacher authoring, source citation checks, compound packs, projects/practice/adaptive context, role-separated exports/shares | Task-specific educational and factual evaluation, one-page vision transcription review, native-speaker acceptance |
| R3 editor | Page workspace, annotations/forms/images, supported native text/image replacement, destructive raster redaction, form templates/batches | Broad real-world PDF font/layout qualification; unsupported encodings explicitly fail |

All **128 feature IDs and 48 tickets are accounted for** in [feature coverage](feature-coverage.md) and [delivery-progress.json](delivery-progress.json). `implemented_local` is different from `provider_dependent`, `partial`, and approved production release. Tests do not prove every pedagogical outcome in the catalog.

## Evidence and release boundaries

[Verification](verification.md) records exact final test runs. [Processor capabilities](processor-capabilities.md) describes engine limits and retained artifact evidence. Customer browser evidence is under `document-web/docs/design`; staff screenshots under `docs/design/admin`; real OCR/editor evidence under `docs/verification/advanced`.

Docker is not installed on this machine, so Compose was not executed. SQLite is used locally. Real Telegram, Stars and AI endpoints require administrator configuration. The development Office runtime is explicitly an alpha build. Parser resource bounds are not equivalent to production network/filesystem containment. No Git push, public deployment, real payment or unsolicited external message has been made.
