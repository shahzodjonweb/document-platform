# Commerce and Telegram integration

The commerce domain is authoritative for paid periods, payment state and refunds. Only plans are sold: there are no credits or packs. A plan is its weekly limits (`apps/core/allowance.py`, counted from jobs), so a payment creates a subscription period and nothing else. Account.plan is a cache refreshed from non-revoked periods and staff assignments. An approved card transfer is the only activation path; opening a payment request never activates access.

## Card transfers

Customers pay in so'm by transferring the plan's price to the owner's card (`apps/commerce/manual.py`). The card, its holder and the Telegram id to alert are saved in Administrator → Integrations; the prices, and a discount with its last day, in `/ops/plans` (`apps/commerce/pricing.py` works out today's price). The customer chooses a plan in the bot or the web app, is shown the card and the exact amount, sends a receipt, and the owner approves or rejects it from the Finance → Payments page. Approval creates the invoice, payment and 30-day period under `provider='manual'`. A refund is recorded after the owner has returned the money from their own bank app, and takes the plan back at once. Nothing renews by itself: the customer pays again.

Telegram Stars was removed on 2026-10-17. Its rows (`OfferVersion`, `Invoice`, `Payment`, `Subscription` and `SubscriptionPeriod` with `provider='telegram_stars'`) stay as history and are never written again; no schema changed.

## Local walkthrough

Run the normal development API with DEBUG=1, DEVELOPMENT_LOGIN_ENABLED=1, ENABLE_BETA_TOOLS=1, LOCAL_SYNC_JOBS=1 and COMMERCE_SANDBOX_ENABLED=1. Sign in with the explicit development login. The local bot simulator and sandbox periods require the canonical account's is_test flag, and sandbox entitlements are ignored outside enabled development mode. Save a card and prices through the admin panel (tests do it with `tests/test_manual_payments.py::configure`, and put an account on a plan with `paid(account, plan)`); the plan seed prices Plus and Premium at 20 000 and 60 000 so'm for 30 days. No money moves locally: any image serves as the receipt, and a staff user in the Finance group approves it.

The browser billing workspace uses the `/api/v1/billing/` endpoints `subscription`, `transactions` and `manual*`. The bot simulator at `/api/v1/telegram/local/messages` runs the real aiogram dispatcher through an in-memory transport, persists owner-scoped chat history, and downloads/uploads real private files. It never connects to Telegram. Use `/start`, `/plans` and its card-payment buttons, `/usage`, file upload, `/tools`, `/settings`, `/done`, `/run` and `/myfiles`. Commands `/create`, `/study`, `/school`, `/teach` and `/editor` open the configured web workspace. Passwords use secure browser entry, not chat.

CLI equivalent after development sign-in:

```sh
DEBUG=1 COMMERCE_SANDBOX_ENABLED=1 .venv/bin/python manage.py telegramlocal /start
```

## Live configuration and workers

Configure the bot token and web application URL in Administrator → Integrations. The token is read through `operations.integrations.telegram_config()`, never command-line arguments. Polling and webhook mode are exclusive. Polling uses a private mode-0600 process lock to prevent duplicate runners after admin-server restarts. Telegram command menus are installed in English, Uzbek and Russian.

Nothing is on sale until the card is saved and enabled in Administrator → Integrations and the plans have a price; a plan without a price is simply not offered. There is no payment provider to configure.

Commands:

```sh
.venv/bin/python manage.py runbot
.venv/bin/python manage.py dispatchtelegram
.venv/bin/python manage.py deliverbot
.venv/bin/python manage.py reconcilepayments
.venv/bin/python manage.py runbatches --once
```

`runbot` drains delivery retries in the background. Webhook deployments need periodic `dispatchtelegram` and `deliverbot`. `reconcilepayments` expires lapsed periods and qualifies referrals; there is no provider to reconcile against, and it takes no flags.

## Invariants and limits

- The amount and plan of a payment request are server-owned: the customer is told exactly what to send, and the owner checks the receipt against it. A request whose amount no longer matches today's price is opened again at today's; a receipt already sent keeps its amount and is reviewed by hand. A payment's charge id is globally unique.
- A card transfer pays for one 30-day period. Nothing renews by itself and nothing is scheduled; the customer pays again. A higher plan bought while a period runs starts at once; the same or a lower plan follows the running period.
- A refund revokes the payment's period, which takes the plan back at once. Jobs already run stay counted in their week. The old grant, ledger and adjustment tables are kept as history; nothing writes them.
- Referrals are counted (first successful task, at most 5 a month) but reward nothing for now.
- Delivery retries have independent status, attempts and backoff. They never reprocess or recharge the job. Failed/blocked deliveries remain visible in durable records. A live HTTP Telegram session cannot deliver test-account files.
- The local simulator requires DEBUG plus explicit opt-in plus a test account. CSRF, authentication and account ownership still apply.
- A batch counts one file task per child against the weekly limit. The whole batch is checked at confirmation, and its children that have not started yet hold their places until they do. Each quoted child is an ordinary core job with a stable idempotency key. A child that fails gives its place back. Partial results retain completed artifacts; repeated run/resume does not duplicate children. Run the dedicated `runbatches` worker for persisted batch parents; the normal worker stays available for ordinary jobs.
- Local batch capabilities: independent document conversion, compression and image sets (Plus 5 / Premium 25 children), plus Premium reusable form batches (25 PDFs). Form batches apply an owned saved template's `content.commands` to existing text fields, pin its version and hash at confirmation, and produce one output per input, each counted as a file task. Missing fields and checkbox/choice controls fail preflight; field overflow fails that child, which is then not counted. Aggregate byte/page caps and every child capability check are enforced server-side. Production release gates remain closed.

Tests cover server-owned prices and discounts, owner boundaries, CSRF, the payment request, receipt review, approval and refunds, referrals, actual aiogram transport, local uploads → real processing → delivery, retry isolation, command menus, process locks, batch partial outcomes and worker crash recovery. Live Telegram delivery still needs configured credentials and staging acceptance; localhost testing does not establish live transport reliability.

## Queue fairness

Asynchronous normal jobs use `apps.core.scheduling`: Premium has priority, while Free and Plus share the standard tier specified by the catalog. Work waiting five minutes moves ahead of unaged work, ordered by age. Within a dispatch window, each account receives one slot before another turn; durable start/publication times rotate accounts within a tier. A pass considers at most 200 candidates and handles at most 20 jobs by default. Processing is non-preemptive; the aging threshold is not a completion-time promise. Synchronous localhost processing bypasses waiting queues deliberately.

`runworker` handles normal jobs only. Start the separate `runbatches` process for asynchronous batch parents, so a large batch cannot block the ordinary worker. Batch parents run in creation order on that dedicated process; every child still obeys ordinary account concurrency and weekly-limit checks. The local synchronous API continues to execute confirmed batches immediately.

`dispatchoutbox` uses the same selection policy for Celery publication. A database lease prevents simultaneous publication of the same row; successful publication remains distinct from completed delivery. Repeated passes do not refill an already full 20-message waiting window. Unknown/lost delivery may be republished after five minutes, and abandoned publisher claims become retryable after 60 seconds. Stale publishers cannot clear newer leases. The job row lock prevents duplicate processing under redelivery. Use one normal worker strategy (`runworker`, or Celery with its dispatcher) and one dispatcher process for predictable publication backpressure; database claims still protect accidental duplicate dispatches.
