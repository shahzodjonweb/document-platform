# Customer anti-bot verification

Configure both channels in **Admin → Integrations → Anti-bot verification**. Saving requires an administrator and a recorded reason. Turnstile secret keys are encrypted alongside other integration secrets and never returned to a browser. A blank secret field retains the saved key.

## Web setup

1. Open [Cloudflare Turnstile](https://dash.cloudflare.com/?to=/:account/turnstile) and create a **Managed** widget for `pdfmaster.orderdesk.live`. Turnstile works even when DNS is hosted elsewhere.
2. Copy its **site key** and **secret key** into the admin fields. Keep `pdfmaster.orderdesk.live` in Allowed hostnames; these are exact hostnames, without schemes, paths, ports or wildcards.
3. Select **Enable web verification** and save with a reason. Production rejects Cloudflare's published test credentials.
4. Test a new private-browser sign-in. Verification normally completes without interaction; a challenge appears when the provider requires one. A provider failure offers Retry or Cancel and cannot submit authentication without a valid proof.

The web check is off until real credentials are configured. Enabling it requires a complete configuration. Deploy the platform before the matching frontend; the frontend requires the new public provider metadata. Once the matching frontend is live, keys can be configured without another deployment. Disable only the web toggle to roll back enforcement while retaining credentials.

Each initial email login, registration, password-reset request, email link, Google OAuth start, Telegram browser challenge and Telegram Mini App login requires a fresh Turnstile proof when enabled. Checks run before the authentication work. Follow-up email codes and already-created OAuth/Telegram challenges retain their existing ownership, expiration, one-use and rate-limit checks. Existing authenticated sessions keep working.

Server validation checks the provider's success flag, exact hostname, `customer_auth` action, five-minute lifetime and browser-session `cdata` binding. A database uniqueness constraint spends each proof only once, including concurrent attempts and upstream failures. Only a hash is stored; receipt hashes expire after one day. The Siteverify request has a bounded timeout and response size and cannot follow redirects with credentials. Network/provider failures fail closed with a safe error. A shared database budget allows at most 120 provider attempts per minute across new and existing browser sessions, with a 20-attempt browser limit; rejected excess attempts do not call the provider. No client IP headers are trusted or forwarded.

## Telegram behavior

Telegram verification defaults **on in production** and off in local development. It needs no external keys and can be changed independently of web verification.

The bot asks for a language first, then shows a randomized eight-button emoji check. The customer makes one choice and continues. Owner-bound callbacks expire after five minutes. Three incorrect choices require a 60-second cooldown, repeated messages do not flood prompts, and successful verification lasts 30 days. An account is not created until verification succeeds. The existing first-upload and account-link continuations remain intact; expired uploads prompt a resend. Payment settlement remains available independently of onboarding.

This native check provides lightweight friction against simple automated abuse. It is not equivalent to Turnstile and cannot prevent determined clients that can interpret the prompt. Existing upload, billing and document-processing quotas remain in force.

## Validation

- `DEBUG=1 .venv/bin/python -m pytest tests apps/commerce/tests -q`
- `DEBUG=1 .venv/bin/python manage.py makemigrations --check --dry-run`
- `DEBUG=1 .venv/bin/python scripts/verify_contract.py`
- Web: `npm run typecheck`, `npm run build`, `npm run check:catalog`, focused anti-bot browser tests.

Upstream: [server validation](https://developers.cloudflare.com/turnstile/get-started/server-side-validation/), [widget configuration](https://developers.cloudflare.com/turnstile/get-started/client-side-rendering/widget-configurations/), [test credentials](https://developers.cloudflare.com/turnstile/troubleshooting/testing/).
