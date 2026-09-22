# Document Bot — implementation plan for an AI coding agent

Version 1.0 • 2026-09-22 • Proposed implementation specification

## 1. Outcome and fixed requirements

Build one document service available through a Telegram bot, a responsive customer website, and a Telegram Mini App. It has three plans: Free, Plus, Premium. Every customer flow, bot message, admin screen, email-free login flow, error, template, and billing explanation supports Uzbek Latin (uz), English (en), and Russian (ru).

Use exactly two source repositories:

1. **document-web**: public website, customer application, Telegram Mini App, customer design system, customer locale files, generated public API client, frontend tests.
2. **document-platform**: API, Telegram bot, processing workers, admin dashboard and Django admin, database, billing, entitlements, analytics, processing adapters, backend locales, infrastructure and operational scripts.

The admin frontend belongs entirely in document-platform. Do not put staff routes, staff API clients, finance data, or an admin build in document-web. Do not create a third shared-contract repository.

Preserve the product sequence:
- Phase 1: PDF file operations.
- Phase 2: AI PDF/PPTX generation and student/school/teacher capabilities.
- Phase 3: visual PDF content editing.

The package specifies the whole roadmap. Release it in increments; never show an unfinished feature as an active paid benefit. Brand name, domains, production Stars prices, and final external AI/editor providers are configurable decisions. They do not block local implementation with fixtures and sandbox adapters. This handoff creates specifications, not deployed software or repositories.

## 2. Read this package in order

1. IMPLEMENTATION_PLAN.md — architecture, behavior, interfaces, database, billing, analytics, delivery and acceptance.
2. UI_UX_SPEC.md — dedicated UI/UX-agent output; routes, flows, tokens, states, accessible multilingual design.
3. feature_catalog.json — 128 stable product feature IDs with categories, release gates and three-plan access.
4. feature_catalog.csv — the same catalog for human review.
5. plan_seed.json — explicit DRAFT staging limits/tariffs; production paid prices are null and checkout is off.
6. AGENT_START_HERE.md — copyable implementation-agent instructions.
7. DELIVERY_BACKLOG.md — 48 ordered tickets, dependencies and acceptance tests.
8. delivery_backlog.json — machine-readable dependencies and complete feature-to-ticket mapping.
9. README.md — package overview and usage instructions.

Precedence: user instructions > this master specification > feature catalog for exact plan access > UI/UX detail > staging examples. If a discrepancy affects money, identity, privacy or repository boundaries, resolve it in an ADR before implementing the affected behavior. Routine implementation choices should not stop the project.

## 3. Recommended architecture and versions

Use a Python modular monolith with separate worker processes. This avoids duplicating billing/business logic between bot and web clients while allowing heavy processing to scale separately.

| Component | Choice | Reason / constraint |
|---|---|---|
| Customer app | Nuxt 4, Vue 3, TypeScript | One responsive browser/Mini App codebase; public pages can use SSR/prerendering |
| Styling | Tailwind, shared CSS tokens, accessible Vue primitives | Follow UI_UX_SPEC; no external design service required |
| Customer state | Server state through generated client; Pinia only for client workflow state | Server remains authoritative |
| API/backend | Python 3.12, Django 5.2 LTS with latest compatible security patch, Django REST Framework | Domain services, ORM, migrations, permissions and staff integration |
| Schema | drf-spectacular / OpenAPI 3.1-compatible tooling | Export an immutable contract and generated TS client |
| Telegram | aiogram 3 adapter integrated with domain services | Bot transport does not own business rules |
| Background work | Celery, Redis, PostgreSQL transactional outbox | Delivery may repeat; application handlers must be idempotent |
| Database | PostgreSQL 17, latest supported patch at implementation | Transactions, constraints, JSON metadata, reporting rollups |
| Storage | Private S3-compatible buckets; local development MinIO-compatible service or private local adapter | Presigned uploads, scoped downloads, lifecycle deletion |
| Admin | Django custom /ops templates, small TypeScript modules, Chart.js, restricted /django-admin | All admin code stays in repo2 |
| File engines | pypdf, qpdf, Pillow, PDFium renderer, isolated LibreOffice, Tesseract | Gate actual supported formats and engine licenses |
| Generated PDF | Controlled HTML/CSS templates rendered by patched WeasyPrint | AI supplies structured data, never executable HTML |
| Generated PPTX | python-pptx from structured slide models | Native editable text/shapes/tables where supported |
| Tests | pytest, Playwright, Vitest, schema/contract checks | Cover real state transitions and outputs |
| Delivery | Docker Compose initially; independently scalable API/bot/workers | Avoid Kubernetes until measured need |

Pin exact compatible versions in lockfiles and container digests after checking current official docs/security releases. Do not treat a floating latest tag or a version in this document as an immutable instruction to skip updates. Django 5.2 is an intentional LTS selection, not a claim it is the newest series. [S4–S7]

The PDF-to-Word engine and phase-3 existing-text editor require quality/licensing spikes. A renderer alone is not a true PDF editor. Do not automatically select PyMuPDF/Ghostscript or a commercial SDK without recording its applicable license and deployment obligations; PyMuPDF documents AGPL/commercial options. [S11]

### Logical topology

~~~mermaid
flowchart TB
  C["Customer web / Mini App"] --> A["Public API and domain services"]
  T["Telegram bot adapter"] --> A
  O["Admin UI in repo2"] --> A
  A --> D["PostgreSQL and outbox"]
  D --> W["Worker queues"]
  W --> S["Private file storage"]
  W --> P["AI / conversion providers"]
  A --> S
~~~

The bot can call Python domain services directly in the same deployment. The web client uses HTTP. Both pass the same authenticated user, policy, quote and idempotency rules.

## 4. Repository layout and contract ownership

### document-web

~~~text
app/
  layouts/              public, customer, mini-app
  pages/                locale-prefixed public and customer routes
  components/           shared primitives and tool/education components
  composables/          useSession, useTelegram, useQuote, useJob
  features/             pdf, generation, study, school, teaching, editor, billing
  stores/               temporary client state only
  middleware/           session/locale routing
locales/                uz.json, en.json, ru.json
generated/api/          generated public contract types/client
public/fonts/           licensed Latin + Cyrillic fonts
docs/design/            tokens, routes, wireframes, screenshots, interaction decisions
tests/                  unit, integration, browser, accessibility
nuxt.config.ts
package.json
pnpm-lock.yaml
.env.example
~~~

### document-platform

~~~text
config/                 settings, URLs, ASGI, Celery
apps/
  accounts/             identities, sessions, preferences
  catalog/              features, release gates, plan versions
  files/                assets, uploads, previews, retention
  jobs/                 quotes, jobs, steps, attempts, artifacts
  billing/              invoices, payments, subscriptions, entitlements
  usage/                grants, reservations, consumption ledger
  ai/                   provider adapters, structured outputs, evaluations
  education/            packs, questions, practice, teacher material roles
  workflows/            saved operations/templates
  analytics/            events, rollups, metrics, exports
  support/              customer cases
  growth/               referrals and optional sponsorship configuration
  operations/           custom admin views and business actions
telegram/               aiogram routers, FSM transport, callbacks, delivery
processors/             pdf, office, ocr, conversion, generation, editor adapters
templates/ops/          admin pages, in this repository
static/ops/             admin JS, charts, versioned design tokens
locale/                 Django translations uz/en/ru
i18n/                   bot catalogs and shared error keys
contracts/              exported public/admin schemas, examples, feature manifest
infra/                  Compose, Dockerfiles, proxy, backup/restore
tests/                  fixtures, contracts, security, payments, output QA
docs/                   ADRs, runbooks, design/admin, API contracts, metric glossary
pyproject.toml
uv.lock
.env.example
~~~

The backend owns feature IDs, authorization, limits, quote calculation, lifecycle enums, error codes and OpenAPI. Export public and staff schemas separately. Repo1 imports only public contracts from a tagged repo2 release artifact pinned by checksum. Never import the backend's staff models into a public generated client. Contract CI detects breaking changes; API v1 remains backward compatible until both clients deploy.

Customer design tokens are authored in repo1 and copied as a versioned artifact into repo2, with checksum/version in an ADR. Translations remain in their owning repo; shared feature names/error-key catalogs are exported from repo2 for frontend translation parity checking. No hidden runtime dependency on the other checkout.

## 5. Release gates and full feature coverage

| Release | Product scope | Public gate |
|---|---|---|
| R0 | design, contracts, identity, plan/usage foundation, admin baseline | internal only |
| R1A | basic PDF tools, Office-to-PDF, private uploads, job history and delivery | free beta |
| R1B | OCR, qualified editable conversions, batch/workflows, subscriptions, paid admin analytics | first paid release after quality/cost tests |
| R2A | AI PDF/PPTX, templates, outline/revision, credits/top-ups | generation quality gates |
| R2B | complete student/school/teacher feature catalog | education and artifact-role gates |
| R3 | visual PDF editor, existing-content edits, redaction/forms automation | engine licensing and recovery tests |

feature_catalog.json is the full feature inventory. Each record includes an ID, category, phase, access by plan, meter and priority. High priority is a demand hypothesis, not measured usage. A job is eligible only when all are true: global feature released, entitlement allows it, parameters fit the plan, input is supported, and the account can reserve the quote. The catalog UI cannot override these checks.

Do not silently omit lower-priority features. Every ID must be implemented and tested, or retained as a visible internal backlog item with release gate and dependency. Future tools are hidden from task menus. A separate clearly labeled roadmap may describe planned functionality without selling it.

Internal operations features are specified in section 17 and are not paid customer features.

## 6. Plans, quotas and policy

Free is permanent basic access, Plus is regular document/AI use, Premium adds larger capacity and advanced workflows. Modes are independent of plans. All three plans share reliable output downloads, privacy controls and payment support.

The attached plan_seed.json contains editable staging defaults:
- Free: 90 standard tasks per 30 days, at most 3 included tasks daily; 500 processed-page units; 30 shared AI credits; 10 MiB/file; 50 pages/job; one running job.
- Plus: 500 tasks, 10,000 page units, 500 AI credits; 50 MiB/file; 200 pages/job; batches of 5; two running jobs.
- Premium: 2,000 tasks, 50,000 page units, 2,000 AI credits; 200 MiB/file; 1,000 pages/job; batches of 25; three running jobs.
- Generation caps: Free sample 2 PDF pages or 5 slides; Plus 10 pages/20 slides; Premium 30 pages/50 slides, with source/token caps in the seed.
- Saved workflows: 0/1/20. Saved teacher templates: 0/5/30.

These numbers are proposed engineering defaults. Benchmark actual conversion/AI cost, completion rates and performance before publishing limits and prices. Production prices are intentionally null; keep live checkout disabled until configured. Sandbox invoice fixtures use test amounts and cannot become production prices accidentally.

Policy details:
1. All sample features consume the same monthly starter-credit pool. They do not create a fresh trial per feature, locale, bot restart or device.
2. Standard operations and AI/OCR credits are different meters. A basic job uses one task plus page units. Page units equal max(total input pages, output pages); images count as pages for image-to-PDF. Office documents are inspected after conversion preflight where necessary.
3. A merge of several files is one job/task within aggregate input caps. Batch conversion is a parent grouping independently metered child jobs. Preview/settings/export do not consume a second task.
4. OCR and qualified editable conversion use the displayed page-based credit tariff, not a hidden extra standard task. AI jobs use versioned source/context/output/provider tariffs and a quoted upper bound.
5. Composite packs and workflows show a total and child breakdown. Shared source ingestion is charged once. Do not charge a full parent fee and duplicate child generation fees.
6. Plus exam pack = summary and questions; Premium adds flashcards and revision plan. Plus lesson pack = plan and worksheet; Premium adds slides, homework and teacher key. Individual included tools remain usable within their normal allowance.
7. Premium image generation is optional per job. Plus posters can use uploaded/approved template imagery; enabling generated images requires Premium entitlement and quote.
8. Canceling renewal preserves access until paid expiry. Unused included grants expire at period end. Purchased top-ups do not expire in v1; referral grants expire after 30 days with that rule disclosed.
9. Consume expiring included grants first, then eligible referral grants, then purchased credits. Preserve purchased balances across plan changes; a top-up never unlocks a feature absent from the current plan.
10. Failures release reservations; confirmed completed work is charged once. A no-op compression that returns no useful smaller output is not charged. Partial batches charge successful children only.
11. Opening a UI or choosing a theme/locale never incurs a hidden charge. AI outline creation can incur a small separately disclosed charge; manually reviewing it and exporting a completed result do not.
12. Limits are evaluated on the server, including for saved templates, batch children and API requests that bypass visible UI controls.
13. Each purchased standard-task pack grants both a disclosed task quantity and processed-page quantity. The Free daily cap applies to included tasks; confirmed purchased-task grants can be used beyond that included cap, subject to normal abuse/concurrency limits. A pack does not raise per-file, aggregate-input, per-job-page or feature limits. Show this before checkout.
14. Merge input count is independent of independent-document batch access: Free can merge several inputs into one PDF even though independent batch jobs are paid. Seed aggregate-upload and merge-file caps are explicit; per-job page limits still apply.
15. Per-feature parameter schemas cap question/card counts, pack components, source context and output length. PlanFeaturePolicy supplies these controls to every client; an AI model cannot expand its own quota.

Free cycles are deterministic 30-day windows anchored to account creation; daily cap boundaries are UTC and explained in the user's timezone. Paid cycles use confirmed provider period dates. Unique grants prevent duplicate allocation across retries. Switching plan, locale, mode, client or cancellation state does not reset a current allowance.

## 7. Identity, browser login and authorization

Canonical user = internal UUID + unique Telegram user ID stored as a signed 64-bit integer. Username/display name is mutable presentation data, never an identity key. Anonymous public website visitors are not registered users. Default locale is selected explicitly or inferred once from a supported Telegram language, falling back to English.

### Mini App authentication
Validate raw initData on the backend using the current official server-validation procedure, freshness (initial target 5 minutes with small clock tolerance), intended bot and timing-safe comparison. Never trust initDataUnsafe or a user ID sent by the frontend. Issue an application session after validation; do not replay raw Telegram data for every API request. [S1]

### Standalone browser authentication
Use a first-party Telegram confirmation flow rather than requiring a second password account:
- Browser creates a 5-minute login challenge bound to an HTTP-only challenge cookie and a verifier/nonce. Store only token hashes.
- Display a Telegram deep link/QR with an opaque, one-use challenge token.
- The bot displays the initiating browser/device description and asks that Telegram user to confirm login.
- Backend binds that challenge to the authenticated Telegram sender.
- Only the original browser with the bound verifier can exchange the approved challenge for a session.
- Tokens expire, are consumed once, and cannot authorize any different browser. A forwarded link alone must not log an attacker in or reveal the approving user's profile. Apply clear confirmation, request fingerprint hints, retry caps and security logging.

Use secure HttpOnly SameSite cookies for ordinary browser sessions behind the same-origin /api proxy. Enforce CSRF on unsafe cookie-authenticated methods. Allow logout/session revocation.

Mini App cookie behavior must be tested on iOS, Android and Telegram Web. If cookies are unavailable, use a separately tested short-lived access token and rotating refresh token held only in memory; validate initData at initial exchange. Do not persist tokens in localStorage. Refresh-token rotation/reuse detection is server-side. After a reload without durable session capability, obtain fresh Telegram launch data; preserve server drafts while re-authenticating.

All asset, draft, quote, job, artifact, project, billing and support endpoints enforce ownership or explicit share grants. An opaque UUID is not authorization. Staff use a separate session realm, MFA and role permissions; customer login must never create staff access.

## 8. Telegram bot behavior and transport

Use webhooks in production and polling in development, never both for the same bot simultaneously. Webhook endpoint verifies Telegram secret header, size and content type, stores a unique update receipt, quickly acknowledges and dispatches normal handling. Deduplicate (bot_id, update_id). The pre-checkout handler is a fast validated path; do not put it behind a long processing queue.

Commands and menus are specified in UI_UX_SPEC. Support /start, /menu, /tools, /myfiles, /plan, /language, /help, /support, /paysupport, /terms, /cancel. Localize BotFather/setMyCommands descriptions and all callback labels.

Implement file-first and action-first FSM flows with server-owned drafts. Store callback tokens as opaque short references bound to user, draft and expiry. A merge accepts multiple messages/albums, explicit Done, preview/order confirmation, quote and Run. Handle updates arriving out of order without guessing final order. Render Telegram HTML through safe escaping, not raw user HTML.

Cloud Bot API download/send limits differ from user upload limits. Official documentation currently states 20 MB for bot downloads and 50 MB for sends; a local Bot API server offers larger transport capacities. [S3] Use the private local Bot API service for R1B paid file limits; configure its API ID/hash and bot token only in repo2 secrets. Route file retrieval through the internal sidecar; never expose its local file paths.

If local Bot API is unavailable, enforce actual channel limits and offer authenticated browser/Mini App upload and scoped result downloads. Do not advertise a 200 MiB bot upload that the deployed transport cannot retrieve. Large web outputs may use authorized download links instead of sendDocument.

Throttle progress message edits and respect retry_after. Telegram delivery is separate from job completion: a completed file with delivery failure is retried by the outbox without reprocessing/recharging. Store returned file IDs as transport metadata; do not use cross-user file deduplication as an authorization shortcut. Bot-blocked users can still retrieve results on the web.

Temporary server deletion does not erase messages or files already delivered into a user's Telegram chat. State this accurately.

## 9. Uploads, storage and job execution

### File lifecycle
create upload intent → transfer into private quarantine → finalize and verify object/size/hash/type → inspect/scan → ready → referenced by job → artifacts ready → expired → deleted.

Browser uploads use short-lived signed upload permissions for an owner-bound object key and size/content restrictions. Finalization checks the actual object, not client-supplied metadata. Bot uploads enter the same FileAsset pipeline. Original filenames are display metadata, not filesystem paths.

Allowlist input types; inspect MIME magic, extension, archive member sizes and maximum expansion ratio. Office ZIP containers require traversal/zip-bomb checks. Reject macros/active embedded content for the initial accepted formats, or process only through a documented isolated policy. Parsing/rendering occurs as a non-root, resource-limited process with read-only engine images, private scratch, timeout, CPU/RAM/temp-disk caps and no network access. Provider-call workers are separate from file-parser sandboxes.

Users can supply a PDF password for the current attempt. Store it only in an encrypted short-lived secret handle, never plaintext in jobs, queues, logs or analytics. Delete the secret on completion/failure/expiry; a retry may ask again.

Inputs, temporary previews and output binaries expire 24 hours after completed work by default, consistently across plans. Retention jobs clean abandoned uploads, job scratch, thumbnails and derived objects; object-store lifecycle is a backstop. Mark history metadata as expired even if asynchronous deletion is still pending; revoked assets cannot be downloaded.

Study sets and adaptive practice require an explicit Save project action. Save only the approved generated question/answer data and necessary cited excerpts, encrypted and owner-scoped, for a disclosed 90-day renewable retention window. Do not silently retain whole uploaded textbooks. Plan storage-slot limits are operational dependencies for saved study features, not a generic cloud drive. Templates/settings/logos persist until deleted or the documented account policy removes them. Financial records have a separately documented minimal retention policy.

### Job lifecycle

~~~text
draft → validating → quoted → reserved → queued → running → finalizing → succeeded
                                           ↘ failed / canceled / expired
batch parent → succeeded / partially_succeeded / failed / canceled
delivery status is independent: pending → delivered / retrying / failed
~~~

A Job stores account, feature, release/version, input asset IDs, validated parameters, output language, quote/policy/tariff snapshots, origin channel, idempotency key, reservation, status/version and attempt count.

- POST /quotes performs entitlement and resource validation and returns an expiring quote, expected meters, affordable status and supported outputs.
- POST /jobs with quote_id + Idempotency-Key locks relevant grant rows, reserves allowances, creates the job and an outbox event in one database transaction.
- An outbox dispatcher enqueues it. Queue publication failure never loses a committed job.
- Workers claim attempts with compare-and-swap/leases, write artifacts atomically, and settle the reservation once. Treat Celery delivery as at-least-once, not exactly-once. [S6]
- Heartbeats and a reaper distinguish slow work from abandoned attempts. Retry only idempotent steps; preserve already-valid child outputs.
- Unknown provider result after timeout requires reconciliation before repeating a potentially billed request; pass provider idempotency keys where supported.
- Cancellation is a request. A queued task can release immediately; a running task settles only after its attempt is stopped or its result is recorded. Canceling a browser view alone is not job cancellation.
- Paid entitlement at quote time is rechecked when reserving. Once accepted, pin the approved policy for that job; expiry during execution does not corrupt already-paid work.
- A requested revision creates a new job against an immutable output version. Updating the same result pointer requires optimistic concurrency to avoid overwriting another revision.

SSE provides stages to the browser where supported; authenticated polling with backoff is the fallback. Never manufacture percentages or delivery ETAs. Every failure returns a stable localized error code and retryability field.

## 10. PDF and AI processing adapters

Use an adapter interface with inspect, validate, estimate, execute, validate_output and capabilities. Record engine/version for every attempt.

| Family | Implementation and quality gates |
|---|---|
| Page operations | pypdf/qpdf; preserve intended page order, rotations and dimensions; reject invalid ranges |
| Images → PDF | Pillow orientation/EXIF handling, defined A4/Letter/custom layout, supported embedded fonts and pixel caps |
| PDF → images/previews | PDFium renderer with DPI/pixel/output-count caps; encrypted input through secret handle |
| Compression | Controlled structural/image optimization; show measurable result; never promise a fixed reduction or rasterize all content silently |
| Office → PDF | Isolated LibreOffice process/profile per attempt; approved fonts; no network/macros; explicit unsupported content warnings |
| OCR | Tesseract eng/rus/uzb and optional uzb_cyrl; scan quality/language selector; do not claim dependable handwriting OCR from printed-text OCR |
| Handwriting | Reviewed vision-provider adapter in R2B; mark uncertainty and allow correction |
| PDF → Word | Engine spike on digital/scanned/multicolumn/table cases; preserve editable text; known limitations, preview and unsupported-case failure |
| PDF tables → Excel | Table extraction adapter with cell/type review; scanned input requires OCR; formula-like extracted strings written as text unless explicitly typed |
| AI PDF | Validated document JSON → approved templates → isolated HTML/CSS renderer → PDF visual/text validation |
| AI PPTX | Validated slide JSON → editable native shapes/text/tables → render preview → inspect layout/overflow; supplied data drives charts |
| Existing PDF editing | Qualified editor SDK/engine; real existing-text changes and image operations must be proven separately from overlays |
| Redaction | Engine-supported removal, flattened revisions where needed and sanitization; text extraction/object/image recovery tests must fail to recover redacted material |

Prefer permissively licensed engine components where feasible, but record each selected package/container/font license, bundled dependency obligations and commercial cost in docs/adr/engine-selection.md. Do not purchase SDK licenses or deploy services as part of merely implementing a local prototype.

### AI pipeline
1. Validate user task, source permissions/caps and output language.
2. Extract source content and page indices in isolated processing; preserve source IDs and page numbers.
3. Estimate input tokens, output size, images and provider cost; create a bounded quote.
4. Generate a JSON-schema-constrained outline; let user edit.
5. Produce structured sections/slides/questions with explicit artifact roles and source references.
6. Validate schema, lengths, citations, arithmetic where applicable, answer counts and grading totals.
7. Render deterministic templates; inspect every generated page/slide for overflow and missing glyphs.
8. Return artifacts and actual settled meters; record provider usage/cost privately.

Uploaded text is untrusted data, not instructions to the coding agent, runtime tools or model system prompt. Models receive no application secrets or arbitrary filesystem/network tools. Sanitize all previews and external links. A document cannot instruct the model to change plans, expose another user's data or fabricate a payment.

Keep provider and model selection configurable by capability (text, vision, image). Use a mock provider for local development and one real approved provider for launch. No specific model or API price is hard-coded into policy. Record input/output tokens, cached tokens, image quantities, model version, quoted/actual cost, attempts and outcome. Prompts, source text and answers must not enter general analytics.

PDF Q&A must return source asset/page references that exist and support the answer; return not_found when unsupported. Do not invent bibliographic entries, curriculum alignment or numerical chart data. Output-language checking and font rendering must cover Uzbek and Russian.

## 11. Education domain and artifact separation

Define reusable schema types: StudySummary, GlossaryEntry, Flashcard, Question, AnswerKey, LessonPlan, Worksheet, Rubric, RevisionSchedule and Presentation.

Questions carry stable ID, type, stem, options if any, expected answer, explanation, marks, topic, difficulty and optional source references. Save user edits separately from generation history. A teacher reviews generated variants, marking criteria and suggested marks; the system does not automatically finalize grades.

Artifact.role is mandatory: user_document, learner_material, teacher_key, teacher_feedback, public_preview. Student-sharing APIs accept only allowed learner roles by default. An answer key is a separate file and authorization path, not merely hidden visually on a page. Shared material links are explicit, scoped, revocable and time-bounded; recipient access does not grant access to the owner's account, billing, sources or other jobs.

Adult-assisted school mode requests grade/subject, not child full name/birthdate/school address. Do not build a child roster or public leaderboard by default. Verify platform age eligibility before onboarding independent child accounts; parents/teachers can generate files on their behalf. This is an implementation requirement, not a claim of compliance with every jurisdiction.

Adaptive practice uses permitted saved practice history; do not infer a learner's ability from one answer as an authoritative diagnosis. Store results with small topic labels and explicit retention. Reference appropriate source material for subject-specific content rather than promising universal correctness.

## 12. API contract to implement

All APIs are versioned under /api/v1. Use UUIDs, UTC ISO-8601 timestamps, integer quantities and XTR amounts; money/cost decimals must not use floating-point arithmetic. Errors have code, message_key, message_params, request_id, field_errors, retryable. User-facing messages are localized; code is stable.

| Endpoint family | Required operations |
|---|---|
| /auth/telegram/miniapp | POST validated Telegram launch exchange |
| /auth/browser/challenges | POST challenge, GET bound status, POST exchange |
| /auth/session | GET current session, POST refresh where applicable, DELETE logout |
| /me | GET profile, PATCH locale/timezone/mode/preferences; explicit deletion request |
| /catalog | GET released feature definitions, controls and effective plan eligibility |
| /plans | GET current publishable plans, prices, limits, release-aware benefits |
| /usage | GET meter balances, grants, expiry/reset timestamps and history |
| /files/uploads | POST upload intent; POST /:id/complete; GET asset metadata |
| /files/:id | GET authorized metadata; DELETE revoke/delete; GET scoped preview/download |
| /drafts | POST/PATCH input configuration with version checks |
| /quotes | POST validated input/operation quote |
| /jobs | POST idempotent submission; GET paginated history |
| /jobs/:id | GET status/results; POST cancel/retry; GET events |
| /artifacts/:id | GET authorized preview/download; POST delivery to linked Telegram |
| /billing/invoices | POST purchase intent; GET server-confirmed payment/activation status |
| /billing/subscription | GET state; POST cancel-renewal, resume-renewal, schedule-plan-change |
| /billing/transactions | GET immutable user-visible payment/credit history |
| /workflows, /templates | CRUD owner-scoped definitions and published template selection |
| /generation/drafts | Outline/style/content edits with optimistic versioning |
| /education/projects | CRUD permitted saved sets/packs; practice sessions and answers |
| /shares | POST explicit artifact-role share; GET/DELETE permitted share |
| /support | POST ticket; GET owner cases/messages |
| /referrals | GET link/qualified balances, never auto-send invitations |
| /editor/documents | Versioned edit sessions, commands, validation and export |
| /webhooks/telegram | Verified Telegram update receiver, not session-authenticated |

Staff endpoints live under /ops/api/v1 with an independent permission matrix and schema. Analytics APIs accept date_from/date_to/timezone/channel/locale/plan_at_event/source/feature/environment as appropriate. Snapshot endpoints require as_of. Return definitions_version, applied filters, freshness, totals and paginated drilldown links.

Quote response must contain quote_id, quote_version, feature_id, plan_version_id, tariff_version_id, input_fingerprints, normalized_parameters, meters[], available_balances, expires_at, output_expectations and limitations. User-readable plan labels alone are insufficient.

All unsafe create/submit endpoints support idempotency where retries can spend money or start work. Reusing an idempotency key with a different request body returns conflict, not the first unrelated response.

## 13. Data model and database invariants

| Model/group | Important fields and invariants |
|---|---|
| User, TelegramIdentity | UUID user; unique telegram_user_id; created_at; first_verified_channel; locale; mode; timezone; test/deletion flags |
| UserPreference, StaffRole | preferences separate from entitlements; staff roles explicit; no customer-controlled is_staff |
| AuthChallenge, Session | hashed nonce/verifier/token, expiry, consumed/revoked timestamps; strict browser binding |
| FeatureDefinition, FeatureRelease | immutable ID, translated label keys, release state, implementation/parameter schema version |
| PlanVersion, PlanFeaturePolicy | immutable effective versions, XTR prices, period, caps, per-feature options, publication actor |
| Subscription, SubscriptionPeriod | provider references, status, renewal flag, plan version, start/end, successful charge |
| Invoice, Payment, Refund | unique provider charge ID; invoice payload hash; integer XTR; explicit type/status; immutable financial facts |
| EntitlementGrant | user, plan, source paid/complimentary/trial, validity range; paid analytics excludes grants without paid consideration |
| UsageGrant, UsageReservation, UsageLedger | bucket, unit, expiry, reserved/consumed/released amounts; immutable transitions and unique source IDs |
| FileAsset, UploadIntent | owner, random object key, type/hash/size/pages, state, encryption/key reference, expiry, classification |
| Draft, Quote | validated asset versions/parameters, policy/tariff snapshots, owner, expiry |
| Job, JobStep, JobAttempt | status/version, lease, idempotency key, engine/provider, origin, timestamps, actual resource use |
| Artifact, ArtifactVersion | owner/job, role, file reference, revision lineage, content schema, expiry |
| DeliveryAttempt, OutboxEvent | dedupe key, destination scope, delivery status, next retry; never recharges generation |
| AIUsage, ProviderRequest | sanitized operational metadata, token/image usage, decimal cost/currency, provider idempotency ID |
| SavedWorkflow, DocumentTemplate | owner or published library, validated steps/layout, version, locale coverage, plan options |
| EducationProject, Question, PracticeAttempt | owner, source references, reviewed versions, results, retention and artifact roles |
| ShareGrant | allowed artifact IDs/roles, token hash, expiry, revocation, permitted recipient context |
| AnalyticsEvent, DailyRollup | event UUID, occurred/received time, environment, plan-at-event, canonical user, feature/channel/source |
| Referral, RewardGrant | inviter/invitee, qualification, unique reward, monthly cap, fraud review state |
| SupportTicket, SupportMessage | user/job/payment links, staff assignment, audited replies; attachment privacy |
| AdminAuditLog | actor, action, target, reason, redacted before/after, timestamp, correlation ID |
| MetricDefinition, ReportExport | semantic version, filters/as_of/timezone, freshness, requester and export expiry |

Database constraints:
- unique Telegram identity, payment provider ID, webhook receipt, idempotency scope, grant source and settlement transition;
- no negative remaining meter balances; reservation/settlement locks are transactional;
- no duplicate entitlement grant for a renewal charge;
- at most one effective renewing subscription contract per account in the product, despite provider capabilities allowing more;
- object/quote/job owner alignment enforced in domain services and tested against direct API access;
- raw charge rows and usage entries cannot be edited through Django admin;
- account merge is disabled initially; any future merge must reconcile identities and ledgers explicitly.

## 14. Billing and subscription state machines

Use Telegram Stars (XTR) for digital purchases inside Telegram. The initial standalone browser checkout opens the same Telegram invoice so there is one billing rail. A second web payment provider is outside v1 and would require an explicit policy/provider design. Server-confirmed successful payment is the activation authority; a client invoice-close event cannot grant access. Provide /paysupport and refund support. [S2]

Current recurring bot invoices use 2,592,000-second periods. Use provider period fields and current API methods for invoices, subscription changes and refunds; verify exact limits on implementation. [S3]

Invoice state: created → presented → pending → paid, or canceled/expired/failed. Refund is a separate linked lifecycle. Subscription state: pending → active → cancel_at_period_end → expired; active can renew; refunded/revoked are explicit exceptional states.

Payment implementation:
1. Create a server invoice intent with owner, purpose, plan/version, price, currency, period and opaque payload.
2. Pre-checkout verifies owner, currency, amount, purchase eligibility, offer version and duplicate-subscription risk quickly enough for Telegram's deadline.
3. Persist successful charge exactly once and validate it against the intent. A renewal validates its original contract/version, not an unrelated newly published price.
4. Atomically create the paid period, entitlement, allowance grants, analytics facts and receipt/outbox action.
5. Return activation status via API; clients refresh entitlement and preserve the draft.
6. Reconcile provider transactions periodically using pagination plus overlapping lookback and ID deduplication; flag missing/orphan receipts rather than inventing payment.
7. Refund through provider first, then record authoritative success and adjust the specific grants/entitlement with an audit reason. Job credit restoration is not a cash/Stars refund.

V1 plan changes are scheduled at the current period boundary; no unimplemented proration. Cancel the old renewal with provider confirmation and preserve already-paid access. At expiry, issue a new-plan checkout that the user confirms; pending choice alone cannot auto-debit a new amount or grant paid access. If a renewal race produces a payment after scheduled cancellation, reconcile it visibly and resolve the duplicate period rather than counting it as a new customer. Later instant upgrades require a separate tested billing ADR.

Fully refunded current subscription periods lose their associated paid grant; do not revoke a different later valid payment period. Used refunded credits may generate an explicit adjustment/debt ledger and review; never silently make balance math inconsistent. Keep fraudulent/complimentary/test cases distinct from ordinary revenue.

## 15. Usage ledger algorithm

Reservation transaction:
- validate quote owner/hash/expiry and current policy;
- lock applicable grant buckets in deterministic order;
- confirm spendable amounts and user/job concurrency;
- allocate reservation portions by grant expiry/type;
- create job and outbox event;
- commit.

Settlement transaction:
- lock reservation;
- if already terminal, return existing result;
- verify valid output manifest and actual approved units;
- consume at most the confirmed reservation;
- release unused amounts to their original eligible grants;
- append immutable ledger entries, completion event and delivery outbox.

If more work becomes necessary, pause and request a new quote; never silently exceed the user's confirmed credit amount. When a reservation spans a grant expiry, finish valid already-reserved work; a release to an expired grant does not revive old credits. Show the restoration accurately rather than suggesting that expired included credits became spendable again.

Bundle children have their own execution/result states and a single parent cost summary. Jobs cannot escape limits by splitting into many children; aggregate count/page/token/concurrency limits also apply at parent level. Provider costs from failed attempts remain in operational profitability reports even when user charges are restored.

## 16. Localization and generated content

Store all source/metadata as UTF-8; use Unicode-capable fonts in browser, admin, PDFs and PPTX. Locale IDs are uz/en/ru; output locale is separate from interface locale. Uzbek Latin is the default Uzbek interface; OCR may accept Cyrillic Uzbek where supported.

Frontend messages use ICU-compatible pluralization; backend/bot messages use matching variable semantics and locale catalogs. Maintain stable error keys rather than translating raw exception strings. CI checks missing/unused keys, placeholders and output encoding.

Test actual strings: O‘zbekcha, o‘qituvchi, g‘oya, qo‘shish, To‘lov; Russian long labels and mixed-script filenames. Normalize apostrophe variants only for search; preserve source text and filenames. Store dates in UTC and format with the user's selected timezone. UI language does not determine timezone or payment currency.

All template families need locale-aware title/caption/bibliography labels, text wrapping and font coverage. Judge generated Uzbek/Russian samples with a language reviewer; schema validation alone does not establish language quality. Admin cannot publish a customer template/plan/error text without all three locale variants or an explicit unreleased locale state.

## 17. Admin panel: all required statistics and operations

Implement a custom staff dashboard in repo2, not just raw Django model lists. UI_UX_SPEC contains the exact /ops route map. All statistics exclude development/sandbox/test data by default and disclose freshness, timezone, filters and definitions.

### 17.1 Acquisition and new-user statistics
- Total canonical registered users as of selected date; new users by day/week/period.
- Registration channel: bot, Mini App, browser; locale; first-touch campaign/referral; unknown remains unknown.
- First successful task count, activation within 24 hours and 7 days, time to first success.
- Signup → accepted upload → first quote → first success funnel.
- Registration cohort retention at D1/D7/D30, with incomplete windows marked not yet observable.
- DAU/WAU/MAU for meaningful authenticated activity; successful-task active users separately.
- Repeat users, inactive users, user mode mix, tool adoption and per-user median usage.

### 17.2 Paid-user and subscription statistics
- Current paid subscribers, split Plus/Premium.
- Current free users and complimentary-plan users separately.
- First-time paying customers, first-time subscribers, ever-paid customers and current paid customers as different metrics.
- Unique renewal customers, renewal transactions and renewal due/success rates.
- Active subscriptions with renewal off, upcoming expirations, failed/missing renewals, expired and reactivated subscribers.
- Free→Plus, Free→Premium, Plus→Premium transitions, scheduled downgrades and actual changes.
- Cohort conversion within 7 and 30 days; source/locale/channel/feature breakdown.
- Churn counts/rates, paid retention cohorts and observed customer value by signup/first-payment cohort.

### 17.3 Payments and unit economics
- Stars collected, refunded and net; subscription versus task-pack versus AI-top-up revenue.
- First subscriptions versus renewals; transactions versus unique purchasers.
- 30-day recurring subscription run-rate in XTR, excluding one-time packs and complimentary access.
- Average revenue per payer, average subscription transaction, observed cumulative revenue per cohort.
- Provider/processing/storage/delivery cost by feature, plan and outcome; failed-job cost included.
- Estimated contribution margin only with a disclosed dated XTR reward estimate; actual withdrawal settlements tracked separately if imported.
- Outstanding refund/support issues, orphan/duplicate payment alerts and reconciliation lag.

### 17.4 Feature, operations and quality statistics
- Per feature: unique users, attempts, completed jobs, failures, cancellations, no-ops, partial batches, downloads.
- Paid conversion following feature/limit exposure, explicitly labeled attribution rather than proven causation.
- Processing p50/p95/p99, queue delay, timeout rate, retries, no-op compression, output size and conversion quality complaints.
- Worker capacity/heartbeats, queue backlog, provider errors, storage growth, cleanup lag and expired files pending deletion.
- AI tokens/images/cost by model/prompt/template/locale; quoted versus actual usage; output regeneration/feedback.
- Locale-specific failures, missing translations and template QA status.
- Referral qualification, rewards/caps, suspicious patterns; sponsor views only if enabled.
- Support cases, median first response/resolution time, payment-related cases and repeat incidents.

### 17.5 Metric contract

| Metric | Exact definition / denominator |
|---|---|
| New users | distinct canonical production accounts with created_at in [from,to); sessions or /start repeats do not count |
| Activated signup cohort | cohort accounts with first succeeded job by created_at + window; only mature cohorts enter finalized rates |
| Active users | distinct users with accepted task, completed practice, or authenticated study interaction; exclude passive reads/webhook delivery |
| First-time payer | user whose first successful non-test monetary purchase occurred in window; retain gross history and separately flag later full refund |
| First-time subscriber | user's first successful subscription purchase, excluding pack-only buyers |
| Current paid subscriber | distinct account with a non-fully-refunded paid subscription period covering as_of; exclude complimentary grants |
| Ever-paid customer | distinct user with any successful paid history; show retained-net variant excluding users whose entire purchase history is refunded |
| Payers in period | distinct accounts with successful charges occurring in window, including renewals and top-ups; not equivalent to new payers |
| Renewal customers | unique accounts with renewal charges in window; renewal transactions are a separate count |
| Renewal success rate | paid renewals for periods due in cohort / subscriptions scheduled to renew in that due cohort; show matured lookback |
| 7/30-day conversion | mature signup cohort with first paid charge within window / eligible mature signup cohort |
| Churn rate | accounts paid at period start whose paid access ended and was not continued by cutoff / accounts paid at start; newly acquired-and-lost customers reported separately |
| Cancel intent | renewal disabled; does not mean paid entitlement already ended |
| Gross/net Stars | sum successful charge amounts by occurred_at; net cash-flow = inflows minus refunds occurring in window |
| Retained cohort revenue | cohort charges less refunds linked to those charges, regardless of refund date; different from period cash-flow |
| Recurring run-rate | sum contractual XTR renewal prices for currently active renewing paid contracts; a separate active-service figure may include cancellation-at-end |
| ARPPU | chosen period net Stars / distinct paying accounts in the same period; disclose net/cash-flow basis and zero denominator |
| Job success | succeeded atomic jobs / (succeeded + failed atomic jobs); cancellations/no-ops excluded and shown separately |
| Batch success | full/partial/failed parent counts separately; never add parents to child throughput |
| Retention Dn | signup cohort users with meaningful activity in defined day bucket / mature eligible signup cohort |
| Cost per successful job | all direct costs in selected job cohort, including failed attempts, / completed jobs; show denominator and unallocated costs |

Use Postgres facts and versioned rollups first; add a warehouse only after measured reporting load. Build aggregate events server-side through the same outbox as domain changes. Client events help diagnose funnels but never create payment/entitlement facts.

AnalyticsEvent fields: event_id, schema_version, occurred_at, received_at, environment, canonical_user_id if known, feature_id, job_id/invoice_id if relevant, channel, locale, mode, plan_at_event, acquisition_source, app_version, safe numeric properties. Never record passwords, raw document text, prompts, answers or filenames in product analytics.

Do not label language as nationality/location. Current-plan segmentation and plan-at-event segmentation must be different filters. All filters apply equally to KPIs, chart series, detail rows and exports. CSV exports escape spreadsheet formula prefixes, preserve metric definitions/filter/timezone and are audited.

### 17.6 Staff permissions and actions

| Role | Allowed |
|---|---|
| Analyst | aggregate statistics and permitted anonymized exports |
| Support | scoped profile/job/payment metadata and support cases |
| Operations | queues, safe retries/cancellations, cleanup and incident controls |
| Finance | payment reconciliation, provider refunds, subscription operations |
| Content manager | translated templates/help text; staged publication |
| Administrator | roles, plan publication, configurations and audited exceptional grants |

No staff role opens document contents by default. Exceptional content access requires a dedicated permission, purpose/reason, retention validity and audit log. Never expose signed storage URLs in routine logs.

Admin mutations require server permissions, validated state transition and audit reason. Quota adjustments append ledger entries; do not edit balance fields. Refunds run through provider adapter and show pending/confirmed states. Plan publication shows old/new prices, affected renewal contracts, effective date and released benefits. Bulk changes require bounded selection and preview; no unbounded production mutation buttons.

## 18. UI/UX agent requirements

The requested UI/UX agent has produced UI_UX_SPEC.md. The implementation coding agent must assign a UI/UX specialist during implementation, use that spec, and deliver:
- information architecture and task flows before screen implementation;
- desktop/mobile wireframes for file tools, billing, AI, education, editor, admin analytics;
- shared tokens/components, light/dark themes and accessible keyboard/touch behavior;
- high-fidelity screens at 390 and 1440 px with Uzbek/Russian long-label cases;
- Mini App real-device safe-area, theme, keyboard and native-button review;
- screen-state coverage for upload/quote/queue/failure/partial-success/expiry/payment-pending;
- concrete visual QA screenshots and issue resolution at every release gate.

Use authentic seeded fixtures for design and test environments only. Production admin must never contain hard-coded statistics. Match public and admin visual systems while keeping different navigation density and permissions. Saved task state must survive navigation and checkout.

## 19. Deployment, CI and operational design

Local development: Docker Compose starts Postgres, Redis, object store, API, bot/polling, standard worker, isolated converter worker and admin. Repo1 runs independently with the API proxy. Provide one documented bootstrap sequence, seed command, three-locale fixtures and mock provider.

Production topology: TLS ingress, web app, API/admin, webhook adapter, private local Bot API, worker groups, private database/Redis/storage. Use different secrets, bots, buckets, domains and provider projects for staging and production. Do not expose database, Redis or Bot API sidecar ports publicly.

Initial worker groups: fast PDF, office/OCR, AI/render, notifications/cleanup. Bound per-user concurrency and give standard traffic a guaranteed processing share; Premium priority must not starve Free. Scale based on queue delay, RAM/CPU and external provider rate limits.

CI in repo2: formatting/lint/type checks, migrations, policy/ledger/payment/analytics tests, parser fixtures, output QA, public/admin schema export and compatibility, locale completeness, container/dependency scans. CI in repo1: lint/type checks, component tests, generated-client compatibility, locale parity, browser/accessibility flows, no staff-client imports.

Deployment order: backward-compatible database expansion → backend compatible API/workers → feature-flagged frontend → canary enablement → contract cleanup later. Roll back flags/images without destroying ledger/history. Destructive migrations require a restore-tested backup and a separate migration plan.

Observability: structured redacted logs with request/job/payment IDs; metrics and traces; alerts for payment reconciliation lag, impossible balances, duplicate settlements, queue age, parser crashes, cleanup lag, missing locales and provider cost spikes. Separate user-facing errors from internal stack traces.

Backups: daily database backup plus continuous/PITR where supported; weekly staging restore drill; documented object retention and configuration recovery. Never restore deleted customer files into active availability during a routine restore without deletion-tombstone reconciliation.

Initial SLO proposals to validate under a stated fixture load: API metadata p95 <500 ms; fast PDF jobs of <=20 pages complete p95 <30 s excluding upload; lifecycle state updates <5 s; analytics freshness <5 min; pre-checkout internal response target <2 s; cleanup within 1 hour of deadline. These are engineering targets, not public speed promises.

## 20. Security and product reliability acceptance

Required tests are risk-based:
- tampered/stale initData, challenge hijack/replay, refresh reuse, CSRF and origin checks;
- cross-user file/job/quote/artifact/payment/share access, including batch children;
- duplicate job request/webhook/payment/renewal with concurrency; no duplicate user, charge, grant or job;
- reservations at quota boundary, expiry while running, retry after timeout and provider uncertainty;
- batch partial failure with successful-child-only charges;
- Office/archive bombs, traversal paths, oversized pixels, malformed PDFs and passwords absent from logs;
- prompt injection cannot call tools/change policy/expose secrets; sanitized previews resist XSS and renderer SSRF;
- teacher keys excluded from learner bundles and shares at API/storage layer;
- all three locales in real output files; meaningful OCR/conversion quality fixture results;
- existing-text editing does not masquerade as an overlay; redacted content is unrecoverable through extraction and object inspection;
- staff roles cannot read forbidden routes or directly mutate ledgers;
- refunds, canceled renewals, expired/complimentary/test accounts reconcile to admin definitions.

Do not test only helper functions that mirror implementation. Test observable invariant failures, real serialized files, browser flows and fixture-based ledger/report totals.

## 21. Delivery milestones and done criteria

R0 done: two repositories scaffolded, staff/customer boundaries enforced, design artifacts reviewed, verified identity unified, locale catalogs complete for shell, plan catalog and ledgers testable, admin shows correct seeded new-user counts.

R1A done: all R1A features complete end to end on bot/browser/Mini App, direct upload→quote→reserve→execute→download, privacy cleanup, no duplicate jobs, Free allowance correct, no live paid checkout.

R1B done: every R1B feature meets engine fixtures, paid transactions/renewals/refunds reconcile, same balance in all channels, comprehensive new/paid-user admin dashboards, local Bot API/fallback meets file promises, real costs support configured prices. Enable paid launch only after this gate.

R2A done: genuine editable PPTX and legible multilingual PDF, outline/revision quotes, valid output previews, provider budgets, no hidden export charge, image/branding entitlements tested.

R2B done: every education catalog feature available according to tier, valid reviewed question/key schemas, correct pack composition, role-separated sharing, saved-practice consent/retention, educator/language review of real examples.

R3 done: actual content editor with documented engine license, appropriate fallback for unsupported fonts/layouts, genuine redaction tests, versioned edits and batch forms, accessible Mini App/browser controls.

Each release includes migration notes, environment examples, runbooks, ADRs, schema artifact, feature-matrix status, test output and screenshots. “Complete” means real data/outputs/transactions, not a menu item, mocked endpoint or generated screenshot.

## 22. Decisions and gates that remain configurable

The coding agent should proceed with defaults and document choices rather than repeatedly asking about reversible details. Production activation still needs real configuration:
- product name/domains, Telegram bot credentials and owner account;
- Stars prices and validated unit economics for released features;
- AI/vision/image provider credentials and data-processing configuration;
- PDF-to-Word and phase-3 SDK choices after accuracy/license/cost spikes;
- hosting/storage credentials, support contact and published retention/terms;
- translated-copy and educational-content review signoff.

Use stubs only behind explicit development flags. Never fabricate payment success, live metrics or supported conversion fidelity to bypass a missing provider. An unresolved provider blocks only its feature gate, not unrelated development.

## 23. Primary references checked

Accessed 2026-09-22. Product architecture, quotas, metric definitions and UX choices are proposed requirements; source links document platform/library facts. Recheck current provider contracts before implementation.

- [S1] Telegram Mini Apps: https://core.telegram.org/bots/webapps
- [S2] Telegram digital goods payments: https://core.telegram.org/bots/payments-stars
- [S3] Telegram Bot API: https://core.telegram.org/bots/api ; file limits: https://core.telegram.org/bots/faq ; local server: https://github.com/tdlib/telegram-bot-api
- [S4] Django supported versions: https://www.djangoproject.com/download/
- [S5] Django admin: https://docs.djangoproject.com/en/5.2/ref/contrib/admin/
- [S6] Celery tasks: https://docs.celeryq.dev/en/stable/userguide/tasks.html
- [S7] Nuxt 4: https://nuxt.com/docs/4.x/getting-started/introduction
- [S8] Tesseract language data: https://tesseract-ocr.github.io/tessdoc/Data-Files-in-different-versions.html
- [S9] pypdf: https://pypdf.readthedocs.io/en/stable/user/installation.html ; qpdf license: https://qpdf.readthedocs.io/en/10.5/license.html (recheck selected release)
- [S10] python-pptx: https://python-pptx.readthedocs.io/en/latest/ ; WeasyPrint: https://doc.courtbouillon.org/weasyprint/latest/first_steps.html
- [S11] PyMuPDF licensing: https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright
- [S12] Accessibility: https://www.w3.org/WAI/WCAG22/quickref/
