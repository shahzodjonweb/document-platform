# Customer authentication and account linking

One customer UUID owns files, jobs, usage, subscriptions and preferences. Optional Telegram ID, Google subject and verified email/password all resolve to that UUID; credentials never create a parallel workspace when explicitly linked.

## Implementation sequence

1. Add nullable Telegram identity, verified email/password and Google identity fields. Preserve all existing Telegram account UUIDs and relations in an additive migration.
2. Register email customers only after they verify an eight-digit code. Use Django password hashing/validation, one-use codes, 15-minute expiry and five attempts. Password reset/change increments a session version to revoke other sessions.
3. Use Google's authorization-code flow with session-bound one-use state, nonce, PKCE and official `google-auth` ID-token verification. Only request `openid email profile`; discard provider tokens after login.
4. Let signed-in customers add email/password, Google or Telegram in Settings. Telegram requires explicit confirmation in the private bot chat and completion in the initiating browser. A method already owned by another customer is rejected; automatic account/data merging is outside this feature.
5. Let administrators configure OAuth client ID/secret, the exact callback and SMTP delivery under Integrations. Encrypt secrets, retain blank secret inputs, audit changes and keep disabled/unconfigured providers unavailable.
6. Verify adversarial API cases, real local email UI flows, bot callbacks, translated layouts, API contract and production builds. Release platform before web through their independent pipelines.

## Security and operational choices

- Existing customer cookies remain valid until the customer's password changes. Password reset revokes all customer sessions; password change keeps the initiating session.
- A matching Google email alone never links an existing customer. Sign in to the existing account and explicitly add Google.
- Provider disablement does not remove stored identities. No unlink control is offered, so a customer cannot accidentally remove their only login method.
- Authentication limits use atomic database counters per normalized email/account and per server-issued browser identity. A low per-IP limit would combine all clients behind the two deployment proxies. Caller-supplied forwarded IP headers are never trusted.
- Expired challenge/limiter rows are removed by the existing cleanup service; consumed email challenges immediately discard pending password hashes.
- PDF Master access logs omit query strings and referrers to avoid retaining OAuth codes/state. Staff sessions remain separate from customer sessions.
- Telegram Stars and Telegram document delivery require a linked Telegram identity. Other document processing works for email/Google customers.

## Configuration

See [Google and SMTP setup](configuration/customer-login.md). Production callback:
`https://pdfmaster.orderdesk.live/api/v1/auth/google/callback`.
Real Google authorization and external mail delivery require the operator's credentials; automated tests use signed test tokens and a private local mailbox.

Protocol references: [Google OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect), [google-auth ID-token verifier](https://google-auth.readthedocs.io/en/latest/reference/google.oauth2.id_token.html), [Django password management](https://docs.djangoproject.com/en/5.2/topics/auth/passwords/).
