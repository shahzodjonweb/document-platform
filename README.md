# PDF Master · document-platform

Django API, Telegram adapter, private document processing and staff operations. The separate customer application is in the sibling `document-web` repository. This repository owns all authorization, usage policy, API contracts and staff assets.

**Current state: working local beta, with production release gates still closed.** The complete 128-feature specification is preserved in [docs/product](docs/product). [Progress](docs/progress.md), [feature coverage](docs/feature-coverage.md) and the [security review](docs/security-review.md) distinguish verified local functionality from unimplemented or unqualified releases. This is not the full AI/education/content-editor roadmap release.

## Start locally

Requirements: Python 3.12 or 3.13, Node 22+, and Chrome for the optional browser tests. PostgreSQL and Docker are not needed for the default local workflow.

```sh
cd document-platform
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
./scripts/dev-api.sh
```

In a second terminal:

```sh
cd document-web
npm ci
npm run dev
```

- Customer application: http://127.0.0.1:3000/en/app
- Customer website: http://127.0.0.1:3000/en
- Staff application: http://127.0.0.1:8000/ops/login
- Public API: http://127.0.0.1:8000/api/v1/auth/session

Use **Use local development account** in the customer app. This creates a real isolated test account with normal limits, files and history; it does not claim Telegram verification. Use **Open local staff workspace** for the separate staff session. The latter is allowed only from loopback with explicit development flags. Production reports exclude test accounts; choose *Development / test* to see local activity.

SQLite is persisted in `db.sqlite3`; private files are in `.private/`. Both are ignored by Git. Development limits are the real draft limits: Free includes 3 tasks daily, 90 tasks per 30-day cycle and 500 processed pages. Neither restarting the app nor changing language resets a grant. A no-op compression is uncharged. API processing errors release reservations.

## What is implemented

- Thirteen locally qualified document operations: merge, split, extract, delete, reorder, rotate, compress, images to PDF, PDF to images, password protection, known-password unlocking, Word to PDF and PowerPoint to PDF. The Office tools appear only when a qualified local engine is available; the bundled alpha runtime is development-only.
- Private MIME-inspected, owner-scoped uploads; short-lived encrypted password handles; quoted task/page charges; transactional reservations, idempotent submission and settlement; downloadable artifacts and history.
- Django sessions with CSRF, validated Telegram Mini App identity, browser-bound one-use Telegram login challenges, localized errors and preferences.
- Telegram polling/webhook transport, owner-bound action callbacks and shared domain workflows. Bot credentials and live-device verification remain external gates.
- Separate staff authentication with production TOTP, explicit roles, acquisition/task/feature analytics, safe CSV exports, support case handling and append-only audit events. Financial reports say unavailable while payment integration is gated; no invented revenue/KPIs.
- Uzbek Latin, English and Russian customer, bot and staff catalogs. Local font assets include their license files.

[Backend API notes](docs/backend-api.md) document exact request/response shapes and current transport limitations. [Processor capabilities](docs/processor-capabilities.md) record engines and actual artifact evidence. Further features stay in the original backlog with explicit release dependencies.

## Configure Telegram and staff

Copy `.env.example` to `.env` for Compose. The direct development script does not automatically source `.env`; export only the variables needed in your shell. Never commit real bot tokens, database URLs, file encryption keys or staff passwords.

For polling, set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, and an HTTPS `TELEGRAM_WEBAPP_URL` when testing the actual Mini App. Leave `TELEGRAM_WEBHOOK_SECRET` unset for polling, then run:

```sh
DEBUG=1 ENABLE_BETA_TOOLS=1 .venv/bin/python manage.py runbot
```

For staff credentials, use `DEBUG=1 .venv/bin/python manage.py setup_staff your-name --role Administrator`. Run management commands with the same `SECRET_KEY` environment as the API so encrypted MFA enrollment remains readable. It prompts for a password and produces a one-time authenticator enrollment URI. Store it securely. Password+TOTP login is separate from customer sign-in; built-in Django sessions do not confer operations access.

For asynchronous local jobs, set `LOCAL_SYNC_JOBS=0` in the API process and run `DEBUG=1 ENABLE_BETA_TOOLS=1 .venv/bin/python manage.py runworker` in another terminal. Its durable outbox is retried without repeating settlement. The optional Celery publisher is `manage.py dispatchoutbox`; do not start multiple queue modes unintentionally.

Run `DEBUG=1 .venv/bin/python manage.py cleanupfiles` regularly. The cleanup command revokes expired files, removes binaries, expires secrets and handles crash-orphaned outputs. Runtime access checks reject expired assets before the physical cleanup runs. Metadata history remains.

## Verification

```sh
DEBUG=1 .venv/bin/python manage.py check
DEBUG=1 .venv/bin/python manage.py makemigrations --check --dry-run
DEBUG=1 .venv/bin/python -m pytest tests -q
DEBUG=1 .venv/bin/python scripts/verify_contract.py
python3 scripts/coverage_report.py --check
npm ci
npm run test:browser
```

Browser tests use installed Chrome and the running local API. Set `PLAYWRIGHT_CHANNEL=chromium` after installing the Playwright Chromium binary if preferred. The staff suite checks login, three-language layouts, mobile overflow, and automated WCAG 2 A/AA issues. Automated checks are not a complete accessibility certification.

Regenerate the public contract with `DEBUG=1 .venv/bin/python manage.py export_contract`. Its checksum is pinned in the customer repo; update its copy and generated types together. Staff contract lives separately in `contracts/admin.openapi.json` and is never included in the customer build.

## Deployment

[Operations runbook](docs/runbooks/operations.md) covers retention, failure recovery, staff enrollment, migration order and the production checklist. [infra/compose.yaml](infra/compose.yaml) describes a pinned local PostgreSQL/Redis/API/worker/web stack:

```sh
cp .env.example .env
# Edit local configuration, then:
docker compose --env-file .env -f infra/compose.yaml up --build
```

Docker is unavailable on the implementation machine, so Compose deployment has not been executed here. It is explicitly a development stack. Live checkout is disabled; Stars prices are unset. Real Telegram transport, production parser/network containment, PostgreSQL concurrency/restore tests, approved providers/licenses, reviewed legal copy and multilingual release signoff remain production gates. No code or configuration in this repository authorizes payment activation or external publishing.
