# Commerce and Telegram integration

The commerce domain is authoritative for paid periods, allowance packs, payment state and refunds. Account.plan is a cache refreshed from non-revoked periods. The core usage service excludes inactive-tier grants and revoked payment grants. A successful Telegram payment receipt is the only live activation path; pre-checkout and invoice creation never activate access.

## Local walkthrough

Run the normal development API with DEBUG=1, DEVELOPMENT_LOGIN_ENABLED=1, ENABLE_BETA_TOOLS=1, LOCAL_SYNC_JOBS=1 and COMMERCE_SANDBOX_ENABLED=1. Sign in with the explicit development login. Sandbox offers and simulations require the canonical account's is_test flag. This implementation uses fixture amounts (50/150 XTR subscription, 25/30 XTR packs), not approved commercial prices. Every related invoice, payment and period carries sandbox=true. Sandbox entitlements and grants are ignored outside enabled development mode.

The browser billing workspace uses the `/api/v1/billing/` endpoints. The bot simulator at `/api/v1/telegram/local/messages` runs the real aiogram dispatcher through an in-memory transport, persists owner-scoped chat history, and downloads/uploads real private files. It never connects to Telegram. Use `/start`, `/buy plus`, the explicit simulate-payment button, `/usage`, file upload, `/tools`, `/settings`, `/done`, `/run` and `/myfiles`. Commands `/create`, `/study`, `/school`, `/teach` and `/editor` open the configured web workspace. Passwords use secure browser entry, not chat.

CLI equivalent after development sign-in:

```sh
DEBUG=1 COMMERCE_SANDBOX_ENABLED=1 .venv/bin/python manage.py telegramlocal /start
```

## Live configuration and workers

Configure the bot token and web application URL in Administrator → Integrations. The token is read through `operations.integrations.telegram_config()`, never command-line arguments. Polling and webhook mode are exclusive. Polling uses a private mode-0600 process lock to prevent duplicate runners after admin-server restarts. Telegram command menus are installed in English, Uzbek and Russian.

Live checkout additionally requires COMMERCE_LIVE_ENABLED=1, a versioned COMMERCE_LIVE_OFFERS mapping with positive integer prices, correct quantities and subscription period2592000, and COMMERCE_OFFER_VERSION. Missing/null prices fail closed. Published versions cannot silently change price, quantity or period; increment the version to publish a different offer. Test accounts cannot buy live offers. No live charges were made while implementing or testing this domain.

Commands:

```sh
.venv/bin/python manage.py runbot
.venv/bin/python manage.py dispatchtelegram
.venv/bin/python manage.py deliverbot
.venv/bin/python manage.py reconcilepayments --local-only
.venv/bin/python manage.py reconcilepayments
.venv/bin/python manage.py runbatches --once
```

`runbot` drains delivery retries in the background. Webhook deployments need periodic `dispatchtelegram` and `deliverbot`; the authenticated webhook receiver fast-paths pre-checkout answers. `reconcilepayments --local-only` expires periods and qualifies referrals without a provider call. Reconciliation without that flag reads real Telegram transactions and flags unknown receipts; it never fabricates subscription periods from incomplete transaction data. A matching authoritative refund transaction confirms a pending or externally initiated refund. Refund uncertainty remains pending until provider confirmation/reconciliation.

## Invariants and limits

- Invoice request amount, plan and allowance quantities are server-owned. Idempotency is bound to account and request contents. A provider charge ID is globally unique.
- Renewal uses Telegram's expiration timestamp. Canceling renewal preserves paid access. Scheduled plan changes take effect at period end and require a fresh checkout for the new plan; no unrequested upgrade charge occurs.
- Purchased packs do not expire or unlock paid features/file caps. Included grants are limited to the active paid period. Refunds revoke only related grants/periods; consumed usage remains in the ledger and creates a review adjustment.
- Delivery retries have independent status, attempts and backoff. They never reprocess or recharge the job. Failed/blocked deliveries remain visible in durable records. A live HTTP Telegram session cannot deliver test-account files.
- The local simulator requires DEBUG plus explicit opt-in plus a test account. CSRF, authentication and account ownership still apply.
- Batch parents consume no allowance. Each quoted child is an ordinary core job with a stable idempotency key. Combined affordability is checked at confirmation; reservation occurs per starting child. Other account activity can affect later children. An unstarted expired quote fails uncharged. Partial results retain completed artifacts and successful-child charges; repeated run/resume does not duplicate children. Run the dedicated `runbatches` worker for persisted batch parents; the normal worker stays available for ordinary jobs.
- Local batch capabilities: independent document conversion, compression and image sets (Plus 5 / Premium 25 children), plus Premium reusable form batches (25 PDFs). Form batches apply an owned saved template's `content.commands` to existing text fields, pin its version and hash at confirmation, and produce one independently charged output per input. Missing fields and checkbox/choice controls fail preflight; field overflow fails that child uncharged. Aggregate byte/page caps and every child capability check are enforced server-side. Production release gates remain closed.

Tests cover server-owned prices, owner boundaries, CSRF, idempotency, subscription renewal/refunds, preserved ledger history, unknown provider results, referrals, support threads, actual aiogram transport, local uploads → real processing → delivery, retry isolation, command menus, process locks, batch partial outcomes and worker crash recovery. Production Telegram/provider integration still needs configured credentials and staging acceptance; localhost testing does not establish live-provider reliability.

## Queue fairness

Asynchronous normal jobs use `apps.core.scheduling`: Premium has priority, while Free and Plus share the standard tier specified by the catalog. Work waiting five minutes moves ahead of unaged work, ordered by age. Within a dispatch window, each account receives one slot before another turn; durable start/publication times rotate accounts within a tier. A pass considers at most 200 candidates and handles at most 20 jobs by default. Processing is non-preemptive; the aging threshold is not a completion-time promise. Synchronous localhost processing bypasses waiting queues deliberately.

`runworker` handles normal jobs only. Start the separate `runbatches` process for asynchronous batch parents, so a large batch cannot block the ordinary worker. Batch parents run in creation order on that dedicated process; every child still obeys ordinary account concurrency and quota checks. The local synchronous API continues to execute confirmed batches immediately.

`dispatchoutbox` uses the same selection policy for Celery publication. A database lease prevents simultaneous publication of the same row; successful publication remains distinct from completed delivery. Repeated passes do not refill an already full 20-message waiting window. Unknown/lost delivery may be republished after five minutes, and abandoned publisher claims become retryable after 60 seconds. Stale publishers cannot clear newer leases. The job row lock and usage ledger prevent duplicate processing/charges under redelivery. Use one normal worker strategy (`runworker`, or Celery with its dispatcher) and one dispatcher process for predictable publication backpressure; database claims still protect accidental duplicate dispatches.
