# PDF Master · document-platform

Django API, Telegram bot, private document processing and staff operations. The sibling `document-web` repository contains the Nuxt customer website, web application and Telegram Mini App. This repository owns authorization, prices and usage policy, all processing, public contracts and the separate staff application.

Private GitHub repositories: [document-platform](https://github.com/shahzodjonweb/document-platform) and [document-web](https://github.com/shahzodjonweb/document-web).

The applications run locally with persistent data, actual document outputs and an explicitly labeled payment sandbox. The original 128-feature/48-ticket specification is preserved unchanged in [docs/product](docs/product). [Feature coverage](docs/feature-coverage.md) distinguishes artifact-tested functionality, provider-dependent implementation and remaining qualification; a menu entry alone is not acceptance evidence.

## Run locally

Use Python 3.12/3.13 and Node 22. Optional OCR requires Tesseract; optional Office conversion requires LibreOffice. SQLite is the default development database.

```sh
cd document-platform
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
./scripts/dev-api.sh
```

In another terminal:

```sh
cd document-web
npm ci
npm run dev
```

- Customer web application: http://127.0.0.1:3000/en/app
- Local bot conversation: http://127.0.0.1:3000/en/app/bot
- Staff sign-in: http://127.0.0.1:8000/ops/login
- Bot and AI configuration: http://127.0.0.1:8000/ops/integrations
- API health: http://127.0.0.1:8000/api/v1/health

Choose **Use local development account** in the customer app and **Open local staff workspace** for the separate staff session. These loopback-only fixtures require explicit development flags. Development accounts have real limits and persisted history. Choose *Development / test* in staff reports to see them; production reports exclude sandbox financial facts and test accounts.

The [local demonstration guide](docs/local-demo.md) gives complete walkthroughs. No public deployment or Git push is needed.

## Telegram credentials are managed in admin

Open **Integrations → Telegram bot**, enter the bot token and username, add a change reason, then save. Use **Test connection** to verify Telegram `getMe`, and **Start local bot** to run the polling process. The runner uses a process lock and prevents duplicate polling. Stop it on the same page. Supply an HTTPS web application URL when testing a Mini App on a real Telegram device; localhost is only reachable on this computer.

Tokens are encrypted in the database and are never returned to a form, API response or audit entry. Local encryption uses the random `.private/integration.key` file with owner-only permissions. **Back up the database and encryption key together.** For a deployment, configure `INTEGRATION_ENCRYPTION_KEY` through the secret manager. Environment variables remain optional fallbacks, not the required setup interface.

The local bot page runs the actual aiogram handlers and shared account/job services with a local transport. It supports commands, inline actions, uploads and real artifact delivery without sending anything to Telegram. This verifies handler behavior; live Telegram connectivity requires your credentials.

## Application functionality

- PDF merging, splitting, selected pages, ordering, rotation, compression, images/PDF conversion, password protection and known-password unlock; Office-to-PDF when an engine is available.
- Printed English, Uzbek and Russian OCR, searchable PDFs, editable Word text extraction and native PDF-table-to-Excel conversion.
- A page-based PDF editor with positioned text, highlights, notes/drawings, Unicode form filling, images/signatures, actual supported text/image replacement, and permanent raster redaction. Exact format limitations appear in [processor-capabilities.md](docs/processor-capabilities.md).
- Batch processing with per-child outcomes and exact-once settlement; saved multistep workflows with signed quote confirmation and recovery leases; reusable templates.
- Document and education authoring with editable outlines, PDF/native editable PPTX exports, explicit source citations, optional structured AI generation, saved consent-based projects and practice results. Teacher answer keys use separate artifacts; share links allow learner artifacts only and support expiry/revocation.
- Shared balance/quotes, task and AI packs, Stars invoice/subscription/refund adapters, sandbox checkout, referral qualification and optional sponsor controls. Production offers remain disabled until deployment configuration explicitly enables reviewed prices.
- Separate staff sessions, password/TOTP enrollment, role management, account/job views, usage grants, support threads and priority queues, audited actions, revenue/retention/activity reports and safe filtered CSV exports. Analyst reports omit payer identifiers.
- English, Uzbek Latin and Russian interfaces, mobile layouts, light/dark themes and local licensed fonts.

**AI setup:** Integrations also contains the provider mode, text/image models and encrypted API key. Local authoring creates real documents from the content you supply and charges zero AI credits; it never pretends to generate AI content. Provider mode performs bounded structured requests only after a confirmed quote. Live provider quality and pricing cannot be qualified without configuration and review. Advanced feature-specific acceptance status is in [feature-status.json](docs/feature-status.json).

## Data, workers and operations

`db.sqlite3` and `.private/` are ignored by Git. Normal binaries expire after 24 hours; saved education content requires consent and expires after 90 days. Changing locale or restarting does not replenish usage. Failed jobs release their reservations, and ineffective compression is uncharged. Password handles expire after ten minutes and are deleted after their task finishes.

For asynchronous development, set `LOCAL_SYNC_JOBS=0` for the API and run:

```sh
DEBUG=1 ENABLE_BETA_TOOLS=1 .venv/bin/python manage.py runworker
```

`runworker` drains ordinary durable jobs. Run `manage.py runbatches` as a separate process for asynchronous batch work so long batches cannot block all ordinary tasks. Polling includes durable result delivery; webhook deployments run `dispatchtelegram` and `deliverbot`. See [commerce operations](apps/commerce/README.md) for financial reconciliation and sandbox isolation. Run `cleanupfiles` regularly to expire files, secrets, drafts, saved projects and revoked shares.

Staff can be enrolled through **Staff access**, or using `DEBUG=1 .venv/bin/python manage.py setup_staff your-name --role Administrator`. Production staff login requires password and TOTP. Run management commands with the same secret configuration as the API. Django's built-in session does not grant operations access.

## Verify

```sh
DEBUG=1 .venv/bin/python manage.py check
DEBUG=1 .venv/bin/python manage.py makemigrations --check --dry-run
DEBUG=1 .venv/bin/python -m pytest tests apps/commerce/tests -q
DEBUG=1 .venv/bin/python scripts/verify_contract.py
python3 scripts/coverage_report.py --check
npm ci
npm run test:browser
```

Browser checks need the running API and installed Chrome. Regenerate the public schema using `manage.py export_contract`, then update the customer copy, checksum and generated types together. The staff schema stays separate. [Verification](docs/verification.md) records current results and evidence.

[Development Compose](infra/compose.yaml) and the [operations runbook](docs/runbooks/operations.md) describe local operations. Production containment, stable Office runtime qualification, live Telegram/payment/AI verification, educational/language review and operational signoff remain release gates. The local demonstration is not a production release approval.

## CI/CD

The [CI/CD runbook](docs/cicd.md) covers the separate production Docker stack, initial server setup, HTTPS routing alongside an existing project, encrypted application configuration, bot activation and rollback. GitHub Actions tests SQLite and PostgreSQL, builds and smoke-tests the production image, then deploys passing `main` releases over SSH.

Both repositories require Actions variables `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` and `DEPLOY_KNOWN_HOSTS`. Without real values, the workflow explicitly reports **Deployment not configured** and makes no server connection. `scripts/deploy/configure_variables.py` can populate and verify both repositories from local credential files.
