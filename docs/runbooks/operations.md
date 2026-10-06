# Operations runbook

## Startup and contracts

Use the README's two-terminal local startup. API owns business state. Customer app proxies `/api` to its configured backend. Customer files are never served by the static server; API download endpoints re-check ownership, state and expiry. All staff code stays here.

Set `DEBUG=0`, a cryptographically strong unique `SECRET_KEY`, explicit hosts and trusted HTTPS origins in a deployed environment. Set a separately managed `FILE_SECRET_KEY` for encrypted one-use PDF passwords. Keep development sign-in, beta tooling and synchronous execution disabled until a reviewed environment-specific flag policy is installed. Production feature gates intentionally cannot be enabled by setting a client variable.

Schema version is public API `1.0.0`, OpenAPI `3.1.0`, policy `draft-staging-v1`, metric definitions `1.0.0`. Files `contracts/public.openapi.json` and `.sha256` are versioned; generated public types belong only in `document-web`. Customer updates must remain compatible with the deployed backend. Every schema change needs regenerated artifacts and client verification.

## Migrations and rollback

1. Back up the database and current configuration; verify restoration in staging.
2. Apply additive migrations (`manage.py migrate`).
3. Deploy compatible backend/worker images with feature gates closed.
4. Deploy the pinned customer application.
5. Run authenticated upload→quote→reserve→process→download smoke tests, ownership tests, ledger reconciliation and retention checks.
6. Enable only release-reviewed capabilities. Never equate a passing local fixture with production approval.

Rollback closes flags and restores prior application images. Do not destroy usage, payment, audit or task history to undo a deployment. Destructive schema rollbacks require an explicit recovery plan. Reconcile deletion tombstones before making any restored binary available; restoring a backup must not revive deleted private documents.

## Retention and workers

Default retention is 24 hours. Run `manage.py cleanupfiles` every five minutes. It revokes expired assets, deletes private files and password secrets, and sweeps old unregistered binaries. A stale lease is terminally released only when the maximum parser timeout guarantees it cannot still commit output. Current task status and artifact authorization checks prevent a stale worker from charging twice.

The production cleanup daemon has a 384 MiB memory ceiling, including Telegram challenge housekeeping. A running container alone is insufficient: CI and live service verification require a full `Deleted N expired files.` cycle without a restart or OOM kill. The scoped `stabilize-cleanup` server operation can raise only this daemon's previous 192 MiB ceiling in place on the authorized 8 GB server; it never restarts containers or updates another service.

`manage.py runworker` drains the durable database outbox. Use `--once` for a bounded operational pass. Do not combine the direct worker with the Celery dispatcher unless reviewing the at-least-once execution model. Duplicate attempts are safe at application claim/settlement boundaries, but production process death and PostgreSQL contention need the documented load gate.

API metadata logs contain correlation IDs and stable errors. General logs and analytics must not contain document contents, filenames, user answers/prompts, passwords, raw session tokens or presigned links. Stored support messages are owner support data, not analytics.

## Staff access

`manage.py setup_staff USER --role ROLE` prompts for credentials and provisions TOTP. Supported roles: Analyst, Support, Operations, Finance, Content manager, Administrator. Reset MFA only via authorized local administration with `--reset-mfa`; it revokes existing staff sessions. Staff login is throttled. TOTP codes are single-use per accepted counter. Ops has an eight-hour opaque, hashed session cookie scoped to `/ops/`, independent of the customer realm.

Analyst sees aggregate reports and anonymized feature CSV. Support can inspect customer/task metadata and resolve cases with reasons. Finance sees currently gated financial views. Operations sees task/system diagnostics. Content manager sees plan/localization status. Administrator may use all implemented operations. There is no staff file-content download endpoint or general impersonation action. Privileged account metadata views and exports are audited.

## Metrics and finance

Acquisition: distinct canonical accounts created in `[date_from,date_to)` after converting selected local midnights to UTC. Channel means first verified channel for acquisition, task origin for job metrics. Production excludes `is_test` accounts. Daily chart, summary and CSV use the same filters. Current plan, payment history and current paid entitlement must never be conflated.

Job success: succeeded atomic tasks / (succeeded + failed tasks) in the accepted-task cohort. No-op and canceled tasks are excluded. Seven-day activation includes only mature signup cohorts; missing denominators display unavailable, not zero percent. Charts provide equivalent tables.

Billing is intentionally closed with null production Stars prices. Financial pages disclose unavailable integration. Never create a payment/paid user from a UI success event or manual account plan field. R1B owns confirmed Stars payments, renewal/refund reconciliation, non-expiring purchased grants and complete revenue/retention definitions.

## Before public release

- Validate the live bot/browser/Mini App canonical account on Telegram iOS, Android and Web, including browser challenge confirmation, CSRF, launch freshness/replay handling and cookie fallback behavior.
- Run PostgreSQL concurrent reservation/duplicate delivery tests, backup/restore and deletion reconciliation.
- Install stable reviewed engines and isolate parsers in a non-root Linux sandbox with network disabled, readonly runtime, memory/CPU/process/temp-disk limits. Local subprocess limits are not full exploit containment.
- Test worker termination/reaper, sandbox file limits, queue fairness and actual transport limits. Observe worker heartbeats; queue depth is not proof of healthy workers.
- Configure reverse proxy TLS, request size limits, shared distributed rate limiting, private storage, monitoring and scheduled retention. Restrict built-in data-maintenance admin separately.
- Complete translated-copy, privacy/support contact, commercial price and provider/license reviews. Keep later release gates closed until their original backlog acceptance evidence exists.

The supplied Compose file is a local integration scaffold with pinned public image digests. It was not run because Docker is absent on this host. Its development switches and shared parser host must not be presented as a completed production deployment.

## Admin-managed integrations and extended workers

Administrators configure Telegram token/username/web application URL and AI text/image models in `/ops/integrations`. Secrets are never redisplayed. Local Start/Stop controls are permitted only in the explicit loopback development realm. A production service manager runs `manage.py runbot` with the same database and encryption configuration; the runner reads the encrypted token from the database.

Preserve `.private/integration.key` with the local database backup. In deployment, supply `INTEGRATION_ENCRYPTION_KEY` through managed secrets and test a restore before rotating it. Studio drafts and saved education content also use this cipher. Losing the key makes encrypted content unreadable.

Use `runworker` for ordinary jobs and a separate `runbatches` process for long batch parents. This prevents a batch of 25 documents from blocking all ordinary work. `dispatchoutbox` is the alternate Celery publisher; do not run competing queue modes without a deliberate deployment topology. A published event remains undelivered until terminal settlement. Polling drains bot delivery retries; a webhook deployment requires `dispatchtelegram` and `deliverbot` workers. Configure recurring `cleanupfiles` and payment reconciliation explicitly in the deployment scheduler.

Local authoring is available only in DEBUG. Production must select a configured AI provider or disabled mode. Live commerce separately requires reviewed, versioned offers and explicit activation. Sandbox test accounts and facts are excluded from production grants and reports even if copied from a development database.
