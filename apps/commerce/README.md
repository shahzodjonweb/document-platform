# Commerce and Telegram integration

The commerce domain is authoritative for paid periods, payment state and refunds. Only plans are sold: there are no credits or packs. A plan is its weekly limits (`apps/core/allowance.py`, counted from jobs), so a payment creates a subscription period and nothing else. Account.plan is a cache refreshed from non-revoked periods and staff assignments. A plan starts in two ways only: a card transfer the owner approved, or an inPAY payment that inPAY itself confirms. Opening a payment request never activates access.

## Card transfers

Customers pay in so'm by transferring the plan's price to the owner's card (`apps/commerce/manual.py`). The card, its holder and the Telegram id to alert are saved in Administrator → Integrations; the prices, and a discount with its last day, in `/ops/plans` (`apps/commerce/pricing.py` works out today's price). The customer chooses a plan in the bot or the web app, is shown the card and the exact amount, sends a receipt, and the owner approves or rejects it from the Finance → Payments page. Approval creates the invoice, payment and 30-day period under `provider='manual'`. A refund is recorded after the owner has returned the money from their own bank app, and takes the plan back at once. Nothing renews by itself: the customer pays again.

## Automatic payments (inPAY)

Customers can also pay online through inPAY (inpay.uz): they choose a plan in the bot or the web app, pay on inPAY's own page with Click, Payme, Uzcard or Humo, and the plan starts by itself (`apps/commerce/checkout.py`; inPAY's API in `apps/commerce/inpay.py`). The owner saves the key and switches it on in Administrator → Integrations → Automatic payments (inPAY). Card transfer and inPAY are switched separately; with both on, the customer chooses.

- **Which API.** A v2 secret key (`sk_live_…`/`sk_test_…`, from the inPAY cabinet: Kassa → API v2 keys) is used when saved; otherwise the classic merchant id and token (v1). v2 payments are opened with an Idempotency-Key (the Checkout's id) and its webhooks are signed; v1 has neither.
- **What grants a plan.** Only inPAY's answer to our own request (`GET /api/v2/payments/{id}`, or v1 `/transactions/`): succeeded, for exactly the Checkout's amount, in so'm, in the mode the row was opened in. A webhook (`POST /api/v1/webhooks/inpay`), the page the customer returns to and the bot's «I've paid — check» button are reasons to ask, never the answer. A v2 webhook with a wrong or old signature is refused once the signing secret is saved (Test connection fetches it with a live key). A payment that does not match its row grants nothing: the row goes to `review` and the owner is alerted in Telegram.
- **Records.** A paid Checkout writes the same Invoice, Payment, Subscription and SubscriptionPeriod a card transfer does, with `provider='inpay'` and charge id `inpay:<inPAY id>`, so limits, "paid until", the finance totals and refunds work unchanged.
- **Late and repeated news.** `paid` and `refunded` are final. Anything else can still become paid: a payment made after the row was marked failed or expired is honoured, because the money is taken. Repeats change nothing.
- **Test keys.** `sk_test_` drives inPAY's simulator and moves no money. With one saved, automatic payment is offered only to the owner (the Telegram ID saved under Card transfer payments), and a paid test writes no Payment and grants no plan: it proves the wiring from button to webhook.
- **Where inPAY sends people and news.** Both addresses are on the customer website's own domain, the one the kassa is registered for (`{web}/{locale}/app/pay/{id}` and `{web}/api/v1/webhooks/inpay`; the website passes `/api` on to the API), so inPAY accepts them with nothing to whitelist.
- **When a webhook never comes.** `cleanupfiles` (every five minutes) asks inPAY about open payments, a few a run and less often as they age, and closes the ones nobody paid after a day. inPAY's request limits are tight (v1: 100 an hour), so a waiting page or bot button makes us ask inPAY at most every 10 to 120 seconds, three times less on v1.
- **Refunds.** inPAY returns money only from its cabinet or support. The owner returns it there, then marks the refund on the payment's page under Payments, which takes the plan back at once.
- **Notices.** The customer is told in the bot when the payment arrives (`PaymentNotice` with `checkout`), and reminded three days before the plan ends; the owner gets a Telegram alert for each payment received and for anything that needs a look (`StaffAlert`).

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

Nothing is on sale until a way to pay is switched on in Administrator → Integrations (the card saved and enabled, or an inPAY key saved and enabled) and the plans have a price; a plan without a price is simply not offered.

Commands:

```sh
.venv/bin/python manage.py runbot
.venv/bin/python manage.py dispatchtelegram
.venv/bin/python manage.py deliverbot
.venv/bin/python manage.py reconcilepayments
.venv/bin/python manage.py runbatches --once
```

`runbot` drains delivery retries in the background. Webhook deployments need periodic `dispatchtelegram` and `deliverbot`. `reconcilepayments` expires lapsed periods and counts invitations, and takes no flags; open inPAY payments are checked by `cleanupfiles`. Invitations are also counted, and their Plus months given, by every `cleanupfiles` run.

## Invariants and limits

- The amount and plan of a payment request are server-owned: the customer is told exactly what to send, and the owner checks the receipt against it. A request whose amount no longer matches today's price is opened again at today's; a receipt already sent keeps its amount and is reviewed by hand. A payment's charge id is globally unique.
- A card transfer pays for one 30-day period. Nothing renews by itself and nothing is scheduled; the customer pays again. A higher plan bought while a period runs starts at once; the same or a lower plan follows the running period.
- A refund revokes the payment's period, which takes the plan back at once. Jobs already run stay counted in their week. The old grant, ledger and adjustment tables are kept as history; nothing writes them.
- Invite friends, earn Plus (`referrals.py`). A friend counts after opening the bot with the inviter's link and finishing a first task, at most 5 a calendar month (Tashkent); the rest wait for the next month. Every 5 counted friends earn Plus, one month more each time (1, 2, 3 … months of 30 days). The months are an ordinary Plus period written by `periods.grant` with provider `referral` and a zero amount: they follow a paid Plus period and wait for a paid Premium one, and the finance report and `/billing/transactions` leave them out. One `ReferralReward` per step (unique per inviter and step) is also the durable bot message (`telegram/referral_notices.py`). Friends counted before invitations earned Plus stay in the totals and never count (`Referral.counts_toward_reward`). Counting runs with every `cleanupfiles` (every five minutes), on `GET /referrals` and the bot's `/invite` screen. The bot opens that screen from `/invite`, the account screen, and the main menu's 🎁 Free gift and 👥 My referrals buttons (both lead to it). A staff-assigned plan wins over a reward period, which is how a misused reward is stopped.
- Delivery retries have independent status, attempts and backoff. They never reprocess or recharge the job. Failed/blocked deliveries remain visible in durable records. A live HTTP Telegram session cannot deliver test-account files.
- The local simulator requires DEBUG plus explicit opt-in plus a test account. CSRF, authentication and account ownership still apply.
- A batch counts one file task per child against the weekly limit. The whole batch is checked at confirmation, and its children that have not started yet hold their places until they do. Each quoted child is an ordinary core job with a stable idempotency key. A child that fails gives its place back. Partial results retain completed artifacts; repeated run/resume does not duplicate children. Run the dedicated `runbatches` worker for persisted batch parents; the normal worker stays available for ordinary jobs.
- Local batch capabilities: independent document conversion, compression and image sets (Plus 5 / Premium 25 children), plus Premium reusable form batches (25 PDFs). Form batches apply an owned saved template's `content.commands` to existing text fields, pin its version and hash at confirmation, and produce one output per input, each counted as a file task. Missing fields and checkbox/choice controls fail preflight; field overflow fails that child, which is then not counted. Aggregate byte/page caps and every child capability check are enforced server-side. Production release gates remain closed.

Tests cover server-owned prices and discounts, owner boundaries, CSRF, the payment request, receipt review, approval and refunds, inPAY payments against a fake inPAY (both APIs, webhooks true and forged, mismatches, test keys, lost webhooks), referrals, actual aiogram transport, local uploads → real processing → delivery, retry isolation, command menus, process locks, batch partial outcomes and worker crash recovery. Live Telegram delivery still needs configured credentials and staging acceptance; localhost testing does not establish live transport reliability.

## Queue fairness

Asynchronous normal jobs use `apps.core.scheduling`: Premium has priority, while Free and Plus share the standard tier specified by the catalog. Work waiting five minutes moves ahead of unaged work, ordered by age. Within a dispatch window, each account receives one slot before another turn; durable start/publication times rotate accounts within a tier. A pass considers at most 200 candidates and handles at most 20 jobs by default. Processing is non-preemptive; the aging threshold is not a completion-time promise. Synchronous localhost processing bypasses waiting queues deliberately.

`runworker` handles normal jobs only. Start the separate `runbatches` process for asynchronous batch parents, so a large batch cannot block the ordinary worker. Batch parents run in creation order on that dedicated process; every child still obeys ordinary account concurrency and weekly-limit checks. The local synchronous API continues to execute confirmed batches immediately.

`dispatchoutbox` uses the same selection policy for Celery publication. A database lease prevents simultaneous publication of the same row; successful publication remains distinct from completed delivery. Repeated passes do not refill an already full 20-message waiting window. Unknown/lost delivery may be republished after five minutes, and abandoned publisher claims become retryable after 60 seconds. Stale publishers cannot clear newer leases. The job row lock prevents duplicate processing under redelivery. Use one normal worker strategy (`runworker`, or Celery with its dispatcher) and one dispatcher process for predictable publication backpressure; database claims still protect accidental duplicate dispatches.
