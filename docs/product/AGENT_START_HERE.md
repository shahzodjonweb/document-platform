# Start here: AI coding-agent implementation instructions

This package plans the complete product. No application repositories have been created or deployed by this planning exercise.

Give your coding agent this whole folder and the prompt below. Allow it to create the two local repositories or work inside your two existing checkouts. Add Telegram/provider/hosting credentials through the normal secret mechanism only when the relevant integration is ready.

The proposed stack is Nuxt/Vue/TypeScript for the customer app and Python/Django for the platform. The user's requirements are the two-repository boundary, three languages, three plans, product phases, UI/UX specialist and comprehensive admin statistics; framework choices are proposed implementation decisions.

## Copyable implementation prompt

~~~text
You are implementing the document/PDF product described by this handoff. Build actual working software incrementally. Read the entire master specification before editing, then load the UI/UX specification, feature catalog, plan seed and delivery backlog.

Required files:
- IMPLEMENTATION_PLAN.md
- UI_UX_SPEC.md
- feature_catalog.json
- plan_seed.json
- DELIVERY_BACKLOG.md
- delivery_backlog.json

Create or use exactly these two source repositories:
1. document-web: public website, customer web app, Telegram Mini App and generated public API client.
2. document-platform: Telegram bot, API, workers, database, billing, analytics, admin UI and infrastructure.

Keep every admin route, admin asset and staff API client in document-platform. Do not create a third shared repository or put the admin frontend in document-web. Repo2 owns the public/admin API contracts, feature policy and financial state.

Fixed product requirements:
- Uzbek Latin (uz), English (en), Russian (ru) across customer UI, bot, admin, messages, errors and output templates.
- Free, Plus and Premium; Premium inherits Plus, Plus inherits Free, except the explicitly optional Free sponsorship surface.
- One canonical Telegram-linked account, subscription, usage ledger and job history across channels.
- Phase 1 file tools; Phase 2 AI PDF/PPTX and student/school/teacher tools; Phase 3 visual PDF content editing.
- All 128 feature IDs remain tracked. Complete the 48 backlog tickets in dependency order and preserve their release gates.
- A dedicated UI/UX specialist must participate in implementation. Use the supplied specialist spec as the starting design, not an excuse to skip wireframes, accessible components or visual QA.

Start with R0, then R1A. Build a real upload → quote → reserve → process → download vertical slice before expanding tools. Continue through each subsequent release in dependency order while dependencies are available. Checkpoint progress so work can resume between sessions.

Work process:
1. Inspect the current workspace, existing repository instructions and existing changes. Preserve user work.
2. Copy these planning files into a versioned docs/product handoff in document-platform; keep a README reference and the needed client design/spec snapshot in document-web.
3. Create docs/progress.md with ticket status, feature implementation/evidence links, decisions, blockers and the next concrete step. Record that this planning package starts with zero implemented application tickets.
4. Establish local environment, contracts, versioned catalogs, identity, authorization, immutable ledgers and admin role boundaries.
5. Ask the UI/UX specialist to produce task flows, mobile/desktop wireframes, tokens and state coverage before coding the corresponding screens. Review Uzbek/Russian text expansion. Store design work and screenshots in the owning repository.
6. Implement one ticket at a time, with small reviewable commits. Backend/domain behavior precedes UI integration. Independent work may run in parallel after contract boundaries are stable.
7. For every feature, implement real behavior, plan checks, localization, failure states, metadata-only analytics and meaningful acceptance verification.
8. Run the release gate before enabling its features. Publish a coverage report proving which catalog IDs work and which remain gated.
9. Update progress after each ticket/milestone and at session boundaries. Continue with the next unblocked dependency instead of stopping after scaffolding or a plan.

Important implementation rules:
- Backend policy is authoritative. Never trust a plan, price, file owner, user ID or credit balance sent by a client.
- Treat webhook/queue delivery as at-least-once. Use database constraints and transactional idempotency to prevent duplicate users, payments, grants, reservations, jobs and settlements.
- Use private files, owner checks, parser isolation, bounded resources, revocable download permissions and actual retention cleanup.
- Verify Telegram initData server-side and bind ordinary browser login to the initiating browser. Keep staff MFA/session permissions separate.
- Use Telegram Stars for the initial billing rail. Payment success must be server-confirmed. A UI callback cannot grant paid access.
- Keep live checkout off while prices are null. plan_seed.json numbers are staging defaults, not validated commercial promises.
- Implement 30-day provider periods and the documented boundary-only plan-change policy. Do not silently invent proration, auto-charge an unconfirmed new plan or lose purchased credits.
- Quotes have versioned policies/tariffs and a confirmed maximum. Exports/manual outline edits do not create hidden AI charges. No-op compression is uncharged.
- Purchased packs and shared trials use explicit grants. Top-ups do not unlock features or raise file-size limits.
- Use real engine/provider adapters behind capability interfaces. Mock adapters are development-only and visibly labeled.
- AI output must use validated schemas, supplied source references and deterministic document/slide templates. Validate actual serialized files and render quality in all three languages.
- An editable presentation contains editable objects. Existing PDF text editing really changes content. Redaction must remove recoverable content; a black overlay is insufficient.
- Separate learner files from teacher keys/feedback at the authorization and export layer. Saved practice is explicit opt-in with limited retention.
- Admin statistics come from production facts and versioned metric definitions. Never hard-code KPI numbers. Distinguish new users, first-time payers, current paid subscribers, renewals, cancellations, expiry and refunds.
- All costs from failed provider attempts remain in internal unit economics, even when user credits are restored.
- Keep secrets, passwords, full documents, prompts, answers and filenames out of general analytics/logs.
- Do not substitute a route, button, mock endpoint or screenshot for a completed feature.

Handle ambiguity without stopping routine progress:
- Follow user instructions first, then the master, exact catalog access, UI/UX details and staging examples.
- Record reversible technical choices in an ADR and proceed.
- A missing commercial provider or license blocks only that adapter/release flag. Implement all independent infrastructure and user flows with explicit development adapters.
- Do not ask the user repeatedly for already-decided repository, language, plan or UI/UX choices.
- Never fabricate credentials, payment success, legal review, commercial license rights, language-review signoff or test results.
- Prepare a concrete, reviewable result before any approval needed for publishing, spending money or external irreversible actions. Local implementation itself should continue.

For every milestone report:
- Working user journeys and catalog coverage.
- Changes in each repository.
- Meaningful verification results, real artifact samples and UI screenshots.
- API/schema/migration versions and rollout/rollback order.
- Actual remaining blockers and the next unblocked ticket.

Your deliverable is working software in the two repositories with a maintainable operational handoff, not a replacement architecture essay.
~~~

## Agent roles during implementation

| Role | Responsibility | Ownership |
|---|---|---|
| Lead implementation agent | Dependencies, contracts, domain consistency, integration and progress | Both repos, with explicit file ownership |
| UI/UX specialist — specifically requested | Flows, wireframes, tokens, layouts, content states, accessibility and visual review | Customer design in repo1; admin design in repo2 |
| Implementation workstreams, if supported | Frontend, backend/bot, admin, processing and QA | Assign non-overlapping work after interfaces are stable |

Do not start many agents making incompatible versions of the same contract. The lead owns integration. If the runtime cannot spawn a specialist, apply the supplied UI/UX spec as a distinct design/review pass and state that limitation.

## First working checkpoint

The first useful result should let a user sign in, upload two PDFs, see a localized server quote, merge them exactly once, download the result and see their task/remaining allowance. The admin should show one new canonical user and one successful task. Demonstrate that behavior in Telegram and the browser with the same account before multiplying the tool list.

## Configuration to collect when needed

Brand/domains; bot token and local Bot API credentials; production Stars prices; provider credentials; hosting/storage settings; support contact; license choice for qualified converters/editor; reviewed public copy. Use environment examples and local fixtures until each integration is ready. Do not put any real secret in this package.
