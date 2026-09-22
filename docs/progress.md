# PDF Master implementation progress

Updated 2026-09-22. The supplied package started with **zero implemented application tickets**. This workspace now contains two independent source repositories, a running local customer app and an implemented backend/staff application. Original requirements and original ticket statuses are preserved unchanged in `docs/product/`; this file and `feature-status.json` are the implementation record.

## Working local journeys

1. Explicit local account → private upload → server quote → transactional reservation → real PDF process → authorized download → receipt, history and remaining balance.
2. Merge two PDFs, reorder inputs, switch to Uzbek, refresh the draft, submit once and download the three-page result. Verified using actual browser requests and serialized PDF inspection. Two browser QA jobs remain clearly marked as test data in the local development account.
3. Password protect a PDF with AES-256 or unlock using a known password. The API uses ten-minute encrypted secret handles; persisted quotes/jobs contain no plaintext passwords. Success/failure clears bound secrets.
4. Real task and page limits, shared 30-day usage grants, daily Free cap, duplicate submission/settlement handling, failure/no-op restoration, owner-only artifacts and 24-hour retention.
5. Separate local staff sign-in or password+TOTP sign-in, role-authorized analytics, canonical-user explorer, job metadata, support resolution with reasons, audited CSV exports and system/retention diagnostics.
6. English, Uzbek Latin and Russian customer/staff screens, locale-preserving drafts, mobile layouts, local licensed fonts, keyboard file ordering and visibly gated checkout.

Telegram Mini App HMAC validation and browser-bound challenge exchange have protocol tests. Bot workflows use the same account/domain state, with offline transport tests. No real bot token was provided, so **live Telegram browser/bot/Mini App identity continuity and delivery are not claimed**.

## Ticket state

“Local implementation” does not approve the original production release gate.

| Ticket | State | Evidence / remaining acceptance |
|---|---|---|
| R0-01 | Local implementation | Two repos, dependency locks, migrations, runnable SQLite baseline, public/staff schemas, pinned Compose definition; Docker stack not executed on this host. |
| R0-02 | Local implementation; review partial | Dedicated UI/UX agent, flows/wireframes/tokens, 390/1440 screenshots, three locales, keyboard targets, contrast checks. Human linguistic and real-device review pending. |
| R0-03 | Protocol implementation; gate partial | Canonical identity, HMAC freshness/replay checks, browser challenge binding, CSRF, separate TOTP staff realm. Live Telegram device/cookie fallback qualification pending. |
| R0-04 | Local implementation | Nuxt app with public/customer layouts, generated public types, checksum pin, real APIs and reload-preserved drafts. |
| R0-05 | Local implementation; gate partial | Atomic grants/reservations/idempotency/settlement; adversarial boundary tests. PostgreSQL contention and full paid-period grant model pending R1B. |
| R0-06 | Local implementation | Role-scoped operations, acquisition and task analytics, timezone-aware filters, audited safe exports, production test-data exclusion. |
| R0-07 | Local implementation; gate partial | Owner support, localized help, errors, startup/runbooks. Full R0 human/security production review remains pending. |
| R1A-01 | Local implementation; gate partial | MIME/page/pixel/container validation, private files, encrypted password handles, preview/retention work. Production parser network/filesystem isolation remains required. |
| R1A-02 | Local implementation; gate partial | Outbox/leases, idempotent jobs, owner history/download, cancellation and cleanup. Live bot delivery retry and worker-kill production load tests pending. |
| R1A-03 | Local implementation | Actual ordered merge, split/extract/delete/reorder/rotate fixtures. |
| R1A-04 | Local implementation | Image orientation/layout, images→PDF and bounded PDF→image archive with actual artifact tests. |
| R1A-05 | Local implementation | Structural compression, actual size results, no-op release and no false reduction promise. |
| R1A-06 | Local implementation; gate partial | AES protection/unlock; multilingual DOCX/PPTX qualification against bundled development engine. Stable deployed Office engine/sandbox still needs review. |
| R1A-07 | Local implementation; gate partial | Localized commands and file workflow, parameter/order controls, quote/run, replay-safe callbacks. Actual Telegram transport not exercised without credentials. |
| R1A-08 | Local implementation; gate partial | Actual browser upload/quote/result, three locales, persisted draft, mobile and accessibility checks. Actual Mini App devices pending. |
| R1A-09 | Partial | Task/page/concurrency caps and clean outputs implemented; priority/fairness under premium load not qualified. |
| R1A-10 | Blocked release gate | Requires configured live Telegram, stable isolated engines, PostgreSQL/load/recovery validation, device/language review and published operational configuration. |
| R1B-01–R1B-09 | Gated backlog | OCR/conversion qualification, paid financial infrastructure, batches/workflows, referrals and full paid analytics remain unimplemented or unqualified. |
| R2A-01–R2A-07 | Gated backlog | AI providers, bounded structured generation, editable PPTX/PDF wizard, revisions and credit purchases are not implemented. |
| R2B-01–R2B-09 | Gated backlog | Student/school/teacher tools, saved practice and role-separated sharing are not implemented. |
| R3-01–R3-06 | Gated backlog | Genuine existing-content editing, recovery-proof redaction and form automation require engine/license qualification and implementation. |

All **128 feature IDs and 48 tickets remain tracked**. See [feature-coverage.md](feature-coverage.md) and [feature-status.json](feature-status.json) for individual status and evidence. No roadmap-only feature is sold as an active benefit. All production release flags remain closed.

## Verification evidence

- Backend/domain/security suite: [tests](../tests) exercises real artifacts and API invariants. Current exact final totals are recorded in `verification.md` after integration finishes.
- Independent review: [security-review.md](security-review.md) documents five found-and-fixed issues, including canonical Telegram replay and orphan-file deletion, and boundaries not established by local tests.
- Customer browser journey and responsive screenshots: `document-web/tests/browser-smoke.mjs` and `document-web/docs/design/screenshots/`.
- Staff Playwright suite: [tests/browser](../tests/browser), three locales at 390/1440, no horizontal overflow; automated WCAG 2 A/AA audit on overview.
- Independent customer axe audit at 390 px: dashboard and actual result have zero detected WCAG 2 A/AA violations after contrast and readable-label corrections. Automated audit is not a complete accessibility or language signoff.
- Actual engine samples and licensing: [processor-capabilities.md](processor-capabilities.md), [engine-selection.md](adr/engine-selection.md), [processors/evidence](../processors/evidence).
- Public contract `1.0.0` / OpenAPI `3.1.0`, metric definitions `1.0.0`, policy `draft-staging-v1`. Use `manage.py showmigrations` for current migration names; deploy additively before compatible backend/workers and client.

## Decisions and external blockers

[ADR 0001](adr/0001-local-architecture.md) records two-repository ownership, explicit local-only identity fixtures, SQLite development and separate staff auth. Local fonts and design tokens are vendored, not runtime cross-repo imports. Production prices remain null. No purchase, external deployment, provider signoff, license acquisition or Telegram sending was performed.

Needed for release: bot token/username and HTTPS host, deployment/private storage and worker isolation, PostgreSQL/backup/restore validation, support/legal copy and multilingual reviewer approval. Later releases additionally need approved AI/conversion/editor providers and commercial prices grounded in measured cost. These are actual release dependencies; they do not excuse fabricated local success endpoints.

Next concrete step: complete the R1A live-channel and deployment gate with configured credentials and a reviewed isolated runtime, then start R1B-01 OCR qualification and the R1B financial/batch implementation in the original dependency order.
