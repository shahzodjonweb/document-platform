# Delivery backlog for the AI coding agent

This is an ordered backlog, not a record of completed software. All tickets start as not_started. The UI/UX specification was produced during planning; the implementation design/screens and code remain to be built.

Dependencies define the safe build order. Work in small reviewable commits, with backend contracts preceding client integration. Parallel work is optional after an interface is stable; the user specifically requested a UI/UX specialist. Do not create extra repositories.

Each of the 128 feature IDs has exactly one owning implementation ticket below. A release gate verifies the combined behavior; it does not replace the feature tickets. delivery_backlog.json is the machine-readable counterpart.

## How to execute a ticket

1. Read its dependencies, the applicable master sections and feature policies.
2. Record a short implementation decision only where the design is non-obvious.
3. Implement real domain behavior, client/bot entry points, three-locale strings and instrumentation.
4. Verify the acceptance statement using meaningful fixtures or user journeys.
5. Record changed files, schema/migrations, verification evidence and any specific blocker.
6. Enable the feature only when its release gate is passed; otherwise retain a disabled flag.

No calendar promises are attached. Estimate each release after its engine/provider spike and the first measured vertical slice. Conversion quality, payment verification, educational review and true PDF editing are the largest uncertainties.

## Release sequence

| Release | Owning feature count | Ticket count | Exit |
|---|---:|---:|---|
| R0 | 8 | 7 | Internal foundation |
| R1A | 26 | 10 | Free file-tools beta |
| R1B | 17 | 9 | Paid document-tools launch |
| R2A | 18 | 7 | AI PDF/PPTX launch |
| R2B | 46 | 9 | Education launch |
| R3 | 13 | 6 | Content-editor launch |

## R0 — Internal foundation

### R0-01 — Create two repositories and a runnable development baseline

**Repository:** document-platform, document-web. **Dependencies:** none.
**Feature IDs:** cross-cutting infrastructure / release gate.

Create the repository trees, Python/Node lockfiles, local Compose services, environment examples, CI skeletons, public/admin schema separation and ADR directory. Seed isolated development data. Export an initial public contract and pin its checksum in repo1.

**Acceptance:** Both checkouts start using the documented commands. No secrets are committed. Repo1 contains no staff routes or staff API client. Repo2 owns the database and business rules.

### R0-02 — Approve the UI/UX foundation and localization model

**Repository:** document-web, document-platform. **Dependencies:** R0-01.
**Feature IDs:** profile.modes, profile.locale.

Assign the requested UI/UX specialist. Implement route maps, task flows, design tokens, component states, locale keys and wireframes for customer and admin. Preserve the language and mode independently of subscription.

**Acceptance:** Review 390 px and 1440 px layouts in uz/en/ru; keyboard and touch paths exist. Uzbek apostrophes and Russian long labels render. A mode or locale change cannot grant a paid feature.

### R0-03 — Implement canonical Telegram identity and secure sessions

**Repository:** document-platform. **Dependencies:** R0-01.
**Feature IDs:** auth.telegram.

Implement verified Mini App initData, browser-bound Telegram login confirmation, one-use challenges, secure sessions, CSRF, logout and staff MFA separation. Record first verified registration channel and stable acquisition data.

**Acceptance:** Tampered/stale initData, replayed challenge, cross-browser exchange, CSRF and customer-to-staff privilege attempts fail. Bot, Mini App and browser resolve to one account without duplicate registration.

### R0-04 — Build the customer shell and generated API integration

**Repository:** document-web. **Dependencies:** R0-02, R0-03.
**Feature IDs:** cross-cutting infrastructure / release gate.

Build public/customer/Mini App layouts, locale routing, authentication, error boundaries, state-preserving navigation and generated public client. Consume release-aware tools/plans. Add safe-area, theme and keyboard adapters.

**Acceptance:** Browser and Telegram shells use the same account. Direct navigation refresh works. Production pages show real API state; fixture mode is explicit. No auth token is persisted in localStorage.

### R0-05 — Implement versioned entitlements and transactional usage

**Repository:** document-platform. **Dependencies:** R0-01, R0-03.
**Feature IDs:** capacity.monthly, usage.balance, billing.quote, billing.failure_restore.

Load the catalog and draft seed without enabling live checkout. Build PlanVersion, UsageGrant, Quote, Reservation and immutable ledger services. Add a test executor and outbox foundation for exercising reserve/settle/release.

**Acceptance:** Concurrent reservations cannot overspend; duplicate settlement is harmless; expired or altered quotes fail. Free trial credits are shared across tools/devices. Failed work releases the correct original grant.

### R0-06 — Build staff shell, roles, audit log and new-user analytics

**Repository:** document-platform. **Dependencies:** R0-02, R0-03.
**Feature IDs:** cross-cutting infrastructure / release gate.

Create localized /ops pages, staff permissions, audit events, server-side analytics outbox, semantic metric definitions and seeded acquisition reports. Keep restricted Django admin separate from normal business operations.

**Acceptance:** Repeated /start events count once. Production defaults exclude test accounts. KPI, chart, drilldown and export share filters/timezone. An Analyst cannot perform finance/admin actions.

### R0-07 — Add support, private diagnostics and foundation gate

**Repository:** document-platform, document-web. **Dependencies:** R0-04, R0-05, R0-06.
**Feature IDs:** support.standard.

Implement owner-scoped support cases, /support and /paysupport, localized help and safe diagnostics. Document bootstrap, contract publishing, secret setup and routine recovery. Complete the R0 design and security review.

**Acceptance:** Support metadata cannot expose another user or private document. A clean machine can run the mocked local stack. Required shell translations and meaningful identity/ledger checks pass.


## R1A — Free file-tools beta

### R1A-01 — Implement private upload, preview and deletion lifecycle

**Repository:** document-platform. **Dependencies:** R0-05.
**Feature IDs:** files.previews, files.retention.

Build owner-bound upload intents, bot ingestion adapter, MIME/hash/page inspection, quarantine, bounded thumbnails, password secret handles, revocation and 24-hour cleanup. Isolate parser processes and object access.

**Acceptance:** Cross-user downloads fail. Archive traversal/bombs, oversized images and corrupt files fail safely. Expired inputs, previews and outputs disappear together; filenames/passwords never enter analytics.

### R1A-02 — Build durable jobs, status, history and safe delivery

**Repository:** document-platform. **Dependencies:** R1A-01.
**Feature IDs:** jobs.progress, jobs.errors_retry, jobs.history.

Create transactional outbox dispatch, job attempts/leases, reaper, atomic output manifests, cancellation, retries and independent Telegram delivery. Expose SSE/polling and paginated history.

**Acceptance:** Worker termination and duplicate delivery do not duplicate charges or jobs. A succeeded job with a blocked bot remains downloadable. Cancellation cannot release a reservation while its attempt still commits work.

### R1A-03 — Implement PDF page operations

**Repository:** document-platform. **Dependencies:** R1A-02.
**Feature IDs:** pdf.merge, pdf.split, pdf.extract_pages, pdf.delete_pages, pdf.reorder, pdf.rotate.

Implement page selection and range validation, merged source ordering, splitting, extraction, deletion, reorder and rotation with the selected permissive engines.

**Acceptance:** Real fixture outputs preserve requested order, page count, dimensions and orientation. Invalid/all-deleted ranges fail without charge. Merge is one task within aggregate caps.

### R1A-04 — Implement image and PDF image conversions

**Repository:** document-platform. **Dependencies:** R1A-02.
**Feature IDs:** pdf.images_to_pdf, pdf.image_layout, pdf.to_images.

Support image orientation, order, margins, paper size and multi-image PDF creation; render selected PDF pages to JPG/PNG with bounded DPI and pixel counts.

**Acceptance:** EXIF orientation, Cyrillic filenames and multiple image sizes render correctly. Large page-image output is bounded and delivered as an appropriate archive or manifest.

### R1A-05 — Implement honest compression and comparison

**Repository:** document-platform. **Dependencies:** R1A-02.
**Feature IDs:** pdf.compress, pdf.compression_preview.

Implement structural/image compression presets, actual before/after bytes, preview and explicit fidelity warnings. Keep text/vector content when the preset allows.

**Acceptance:** Fixtures verify readable outputs. Already-optimized PDFs produce a no-op outcome and no charge. UI does not claim a fixed compression percentage or use a larger result as a success.

### R1A-06 — Implement Office conversion and password operations

**Repository:** document-platform. **Dependencies:** R1A-02.
**Feature IDs:** convert.word_to_pdf, convert.pptx_to_pdf, pdf.protect, pdf.unlock_known.

Run isolated LibreOffice conversions with approved fonts and no network/macros. Implement PDF encryption and removal using the supplied password; record engine limitations.

**Acceptance:** DOCX and PPTX samples render in all locales. Wrong passwords fail without leaking secrets. Concurrent Office jobs use separate profiles and temporary paths.

### R1A-07 — Deliver complete Telegram file workflows

**Repository:** document-platform. **Dependencies:** R1A-03, R1A-04, R1A-05, R1A-06.
**Feature IDs:** bot.upload_forward, bot.detect_actions.

Implement localized commands, file-first/action-first drafts, album collection, explicit Done, reorder confirmation, quote and run. Deduplicate webhook updates; bind callback references to owner/expiry.

**Acceptance:** From Telegram, a user completes each core operation without opening the web app. Forwarded files are inspected normally. Out-of-order updates or repeated buttons cannot silently reorder files or spend twice.

### R1A-08 — Deliver web and Mini App file workspaces

**Repository:** document-web. **Dependencies:** R0-04, R1A-07.
**Feature IDs:** profile.preferences, capacity.file_size.

Build drop zone, tool settings, thumbnails, accessible page sorting, limit checks, server quote, progress/result/history and language-preserving preferences. Support manual upload fallback for Telegram transport limits.

**Acceptance:** Every R1A tool works end to end through the actual API in three locales. Refresh, language switch, checkout placeholder and back navigation preserve drafts. Client-only limit changes cannot bypass server policy.

### R1A-09 — Finish capacity scheduling and clean output policy

**Repository:** document-platform. **Dependencies:** R1A-02.
**Feature IDs:** capacity.queue, files.no_watermark.

Implement per-user concurrency, queue classes with a guaranteed standard share, page/task meters, safe output names and result manifests. Outputs contain no platform watermark in every plan.

**Acceptance:** A premium-load fixture cannot indefinitely starve standard work. Caps are enforced across simultaneous clients. Generated output bytes and downloads match the settled manifest.

### R1A-10 — Pass the free beta release gate

**Repository:** document-platform, document-web. **Dependencies:** R0-07, R1A-08, R1A-09.
**Feature IDs:** cross-cutting infrastructure / release gate.

Run cross-channel fixtures, parser containment checks, multilingual visual QA, deletion tests and worker recovery. Publish release notes, schema artifact and runbooks; enable only completed R1A features.

**Acceptance:** A new user can register, process, download and find history in all clients. Free limits match the ledger. Live paid checkout remains disabled; production dashboards contain no fixture metrics.


## R1B — Paid document-tools launch

### R1B-01 — Implement OCR with quality and credit metering

**Repository:** document-platform. **Dependencies:** R1A-10.
**Feature IDs:** ocr.extract_text, ocr.searchable_pdf.

Add printed-text OCR language selection, text export and a searchable PDF text layer. Charge the quoted page tariff and expose uncertainty/quality limitations.

**Acceptance:** Ground-truth eng/rus/uzb scan fixtures are measured and reviewed; search finds expected text at sensible page coordinates. Source images remain readable; scanned pages are not charged twice.

### R1B-02 — Qualify and implement editable Word and table conversion

**Repository:** document-platform. **Dependencies:** R1B-01.
**Feature IDs:** convert.pdf_to_docx, convert.pdf_to_xlsx.

Compare engine licenses/cost and real multicolumn/table/scanned fixtures. Record selection ADR, implement editable DOCX and reviewed XLSX cell extraction with OCR when required.

**Acceptance:** Output is genuinely editable. Unsupported layouts receive accurate limitations. Spreadsheet formula-like extracted strings are safe text by default. Disable unqualified formats rather than fabricating support.

### R1B-03 — Implement batches and saved workflows

**Repository:** document-platform, document-web. **Dependencies:** R1B-02.
**Feature IDs:** batch.convert, batch.compress, batch.image_sets, workflow.saved, workflow.reuse.

Create parent/child execution, sequential workflow validation, saved parameter versions, aggregate caps, cost breakdown and downloadable successful output bundles.

**Acceptance:** A batch with one failed child charges successes only and can retry just the failed child. Limits apply to the full batch, including direct API submissions. Shared source preparation is not billed twice.

### R1B-04 — Provision larger Telegram transport and fallback paths

**Repository:** document-platform. **Dependencies:** R1A-10.
**Feature IDs:** cross-cutting infrastructure / release gate.

Document and integrate the private local Bot API sidecar and secrets. Test paid-size uploads/sends and strict internal paths. Make actual transport capabilities available to clients.

**Acceptance:** A 200 MiB premium input works through the deployed intended path or gets an honest authenticated web fallback. Database, Redis and local Bot API ports are not public.

### R1B-05 — Implement Stars subscriptions and financial reconciliation

**Repository:** document-platform, document-web. **Dependencies:** R0-05, R1A-10.
**Feature IDs:** billing.stars, billing.subscription.

Build invoice intents, fast pre-checkout, authoritative successful-payment handlers, paid periods, unique grants, cancellation/resume, boundary plan changes, reconciliation and provider refunds. Build billing UI and bot commands.

**Acceptance:** Replay/parallel payment fixtures create one payment and grant. Renewal honors its original contract. Canceling renewal preserves current access. Client success events cannot activate a plan. Refunds affect only the relevant paid period.

### R1B-06 — Implement task packs and shared starter credits

**Repository:** document-platform, document-web. **Dependencies:** R1B-05.
**Feature IDs:** billing.task_pack, billing.trial.

Add explicitly priced operation-pack offers with task/page grants, expiration disclosure and immutable receipts. Show included, purchased and starter balances separately; preserve purchased balances after subscription expiry.

**Acceptance:** One purchase cannot be replayed into duplicate credits. Top-ups do not unlock larger-file or feature entitlements. Samples share one pool; a user sees exactly which limits a pack changes before buying.

### R1B-07 — Complete paid-user, revenue, retention and operations analytics

**Repository:** document-platform. **Dependencies:** R0-06, R1B-05, R1B-06.
**Feature IDs:** support.priority.

Implement every admin metric in master section 17, detail drilldowns, saved filters, safe exports, support queues and audited finance actions. Add explicit as_of snapshots and versioned definitions.

**Acceptance:** Hand-calculated fixtures include new/free/complimentary/test users, first purchases, top-up-only buyers, renewals, cancel-at-end, refunds, expiry and reactivation. Totals reconcile with financial facts; no double counting parents/children.

### R1B-08 — Implement optional referrals and sponsorship controls

**Repository:** document-platform, document-web. **Dependencies:** R1B-06, R1B-07.
**Feature IDs:** growth.referral, growth.sponsor, growth.ad_free.

Implement user-initiated referral sharing, explicit reward qualification/caps, fraud-resistant unique grants and revocation policy. Add a separately disabled sponsor module restricted to eligible general-mode Free surfaces.

**Acceptance:** No automatic invitations or promotional broadcasts occur. Plus/Premium and school/child flows do not show sponsors. Attribution is not presented as proven causation; disabled sponsorship does not create an empty ad placeholder.

### R1B-09 — Pass paid-launch economics and operational gates

**Repository:** document-platform, document-web. **Dependencies:** R1B-03, R1B-04, R1B-07, R1B-08.
**Feature IDs:** cross-cutting infrastructure / release gate.

Benchmark representative file loads and real unit costs; publish validated prices/limits only through versioned admin configuration. Complete sandbox purchase, renewal, refund, restore and multilingual checkout review.

**Acceptance:** All R1B catalog IDs are covered. Paid checkout cannot activate with null price or unreleased benefits. Payment reconciliation, backups, alerts, support contact and privacy copy are operational before production activation.


## R2A — AI PDF/PPTX launch

### R2A-01 — Build bounded AI providers, sources and outline pipeline

**Repository:** document-platform. **Dependencies:** R1B-09.
**Feature IDs:** ai.language, ai.length_style, ai.outline.

Add capability-based providers, structured document/slide schemas, source extraction/token caps, language checks, versioned tariffs and quote bounds. Implement generated outlines and free manual outline editing.

**Acceptance:** Prompt injection cannot change policy or invoke arbitrary tools. Provider timeout/unknown status reconciles before retry. Malformed outputs fail safely. Every paid outline action has a quote; manual changes do not spend credits.

### R2A-02 — Generate multilingual PDFs from topics, text and sources

**Repository:** document-platform. **Dependencies:** R2A-01.
**Feature IDs:** ai.pdf_topic, ai.pdf_text, ai.pdf_sources, export.generated_pdf.

Implement approved HTML/CSS templates, constrained structured sections, headers/footers/TOC where selected and isolated rendering. Validate PDF text, page count, fonts and layout.

**Acceptance:** Real Uzbek/English/Russian outputs are readable without missing glyphs or clipping. Source references are real. Completed exports/downloads do not add an undisclosed charge.

### R2A-03 — Generate editable presentations and speaker notes

**Repository:** document-platform. **Dependencies:** R2A-01.
**Feature IDs:** ai.pptx, ai.source_to_slides, ai.speaker_notes, export.generated_pptx.

Generate native editable slide text, tables, shapes, charts from supplied data, speaker notes and preview/PDF output where selected. Keep source IDs and slide versions.

**Acceptance:** PPTX text and shapes can be edited in compatible presentation software. Slide render checks find overflow. The engine does not substitute a deck of screenshot-only slides for an editable deliverable.

### R2A-04 — Implement templates, branding and optional images

**Repository:** document-platform, document-web. **Dependencies:** R2A-02, R2A-03.
**Feature IDs:** template.basic, template.professional, template.branding, ai.images.

Create previewed basic/pro templates, Premium logos/colors, safe asset storage and optional metered illustrations. Produce three-locale template fixtures and versioned publication controls.

**Acceptance:** Plus gets professional templates without Premium branding/image access. Uploaded logos cannot execute content or leak external requests. Image generation is explicitly selected and quoted; it is not silently enabled.

### R2A-05 — Implement targeted content and slide revisions

**Repository:** document-platform, document-web. **Dependencies:** R2A-02, R2A-03.
**Feature IDs:** ai.rewrite, ai.regenerate_slide.

Support rewrite/simplify/shorten/expand and selected-slide regeneration through new quoted jobs against immutable artifact versions. Preserve manual edits and use optimistic concurrency.

**Acceptance:** A one-slide revision does not silently bill an entire deck. Two concurrent edits cannot overwrite each other. Users can identify the latest successful version and retain valid prior exports until expiry.

### R2A-06 — Add paid AI credit packs and cost reports

**Repository:** document-platform, document-web. **Dependencies:** R1B-06, R2A-01.
**Feature IDs:** billing.ai_topup.

Add AI-credit invoices for eligible paid plans, non-expiring purchased grants, provider usage accounting, model/template/locale reports and budget alerts.

**Acceptance:** Purchasing credits never unlocks Premium-only tools for Plus. Failed provider attempts count in operating cost but do not create a successful user charge. Display quote/actual usage and remaining purchased balance.

### R2A-07 — Complete generation wizard and release QA

**Repository:** document-web, document-platform. **Dependencies:** R2A-04, R2A-05, R2A-06.
**Feature IDs:** cross-cutting infrastructure / release gate.

Build Content → Outline → Style → Generate, source upload, preview/revision, exact or bounded quotes, payment resume, bot entry and Mini App continuity. Resolve UI/UX findings on real devices.

**Acceptance:** All R2A features pass output, entitlement and three-locale UI fixtures. Closing a view does not imply job cancellation. Drafts survive purchase/navigation. Publish real provider limitations and cost-calibrated allowances.


## R2B — Education launch

### R2B-01 — Implement core study tools and source-grounded Q&A

**Repository:** document-platform, document-web. **Dependencies:** R2A-07.
**Feature IDs:** study.summary, study.definitions, study.flashcards, study.quiz, study.answer_key, study.pdf_qa.

Implement validated study schemas, summaries/glossaries, flashcards, question types/answers/explanations and page-cited PDF Q&A. Build review and optional save controls.

**Acceptance:** Citations open the correct source page and support the answer; unsupported questions return not_found. Answer keys remain attached to the right question version. Generated sets fit quoted quantity limits.

### R2B-02 — Implement study packs, handwriting and writing tools

**Repository:** document-platform, document-web. **Dependencies:** R2B-01.
**Feature IDs:** study.exam_pack, study.handwriting, study.report_format, study.references, study.writing_feedback, study.revision_plan.

Compose Plus/Premium exam packs, reviewed handwriting transcription, report layout, supplied-reference formatting, writing feedback and schedules based on user dates/time. Reuse source ingestion once.

**Acceptance:** Uncertain handwriting is editable before export. References are not invented. Plus and Premium pack contents match policy; separate included tools remain available. Costs do not duplicate parent and child work.

### R2B-03 — Implement school learning and worksheet tools

**Repository:** document-platform, document-web. **Dependencies:** R2B-01.
**Feature IDs:** school.explain, school.examples, school.hints, school.check_attempt, school.similar_problems, school.worksheets, school.reading, school.vocabulary, school.adult_mode.

Build grade/subject context, age-appropriate explanations, hints, attempts/feedback, similar problems, worksheets, reading and vocabulary. Support adult-assisted generation without collecting child identity.

**Acceptance:** Representative questions and arithmetic are checked; outputs receive educator/language review. UI encourages attempting exercises and labels generated feedback. Child full name, birthday and school are not required.

### R2B-04 — Implement saved results and Premium adaptive practice

**Repository:** document-platform, document-web. **Dependencies:** R2B-03.
**Feature IDs:** school.weekly_pack, school.adaptive, school.results, school.weak_topics.

Create explicit opt-in saved projects, bounded practice attempts, topic signals, weekly packs, follow-up exercises and deletion/90-day renewal flows. Use minimal owner-scoped learning data.

**Acceptance:** No persistent learner history exists before consent. Weak-topic recommendations have visible supporting attempts. Cross-user/project access fails. Limits and retention apply across Free/Plus/Premium.

### R2B-05 — Implement school project outputs

**Repository:** document-platform, document-web. **Dependencies:** R2B-03.
**Feature IDs:** school.project_outline, school.project_slides, school.poster.

Produce outlines based on learner ideas, project slides/speaking notes and printable posters. Use the shared generation/branding/image entitlement services.

**Acceptance:** Plus posters can use supplied/template imagery; generated illustrations require Premium and explicit quote. Project output is editable where promised and readable at print size.

### R2B-06 — Implement lesson planning and teacher packs

**Repository:** document-platform, document-web. **Dependencies:** R2B-01.
**Feature IDs:** teacher.lesson_plan, teacher.lesson_pack, teacher.worksheet, teacher.homework, teacher.reading_level, teacher.syllabus.

Implement lesson objectives/duration, plan, worksheet, homework, reading-level adaptation, syllabus-to-weekly outline and tier-specific lesson-pack composition.

**Acceptance:** Teacher can review/edit objectives and questions. Plus lesson pack contains plan/worksheet; Premium composition includes configured slides/homework/key. Curriculum claims require supplied references.

### R2B-07 — Implement assessments, variants, rubrics and feedback

**Repository:** document-platform, document-web. **Dependencies:** R2B-06.
**Feature IDs:** teacher.mcq, teacher.written_test, teacher.answer_key, teacher.variants, teacher.differentiated, teacher.rubric, teacher.feedback, teacher.suggest_marks.

Build MCQ/written questions, marks/explanations, A/B/C variants, differentiated worksheets, rubric generation and draft feedback/mark suggestions with review state.

**Acceptance:** Question IDs, variant/key pairing and mark totals are consistent. Answers are not accidentally included in student exports. Suggested marks stay drafts until the teacher confirms.

### R2B-08 — Implement teacher templates, branding and safe sharing

**Repository:** document-platform, document-web. **Dependencies:** R2B-07.
**Feature IDs:** teacher.saved_templates, teacher.branding, teacher.separate_exports, teacher.share_materials.

Add tier-limited reusable class-level layouts, Premium school branding, mandatory artifact roles, learner/teacher export selection and explicit revocable sharing to unpaid recipients.

**Acceptance:** A learner share cannot access keys, private feedback, original source, billing or sibling artifacts, even by URL manipulation. Share preview lists exact included artifacts; revocation/expiry works at the API/storage level.

### R2B-09 — Complete education UX and content-quality gate

**Repository:** document-platform, document-web. **Dependencies:** R2B-02, R2B-04, R2B-05, R2B-08.
**Feature IDs:** cross-cutting infrastructure / release gate.

Finish Student/School/Teacher workspaces, interactive practice, bot/Mini App handoff and educator-reviewed fixture library in three languages. Add generated-material feedback and privacy runbooks.

**Acceptance:** Every R2B catalog ID is mapped to an implementation and acceptance result. Saved practice has actual deletion; packs charge once; student and teacher materials stay separated in all clients and exports.


## R3 — Content-editor launch

### R3-01 — Qualify the PDF editor engine and workspace

**Repository:** document-platform, document-web. **Dependencies:** R2B-09.
**Feature IDs:** editor.visual.

Run the existing-text/image/redaction/forms/font/license spike before engine commitment. Implement canvas/pages/tools/properties, immutable versions, command validation and recoverable edit sessions.

**Acceptance:** Record measured supported/unsupported PDF cases and commercial/license obligations. Mini App can open the same owned document/session as browser. An overlay-only demo does not satisfy existing-text editing.

### R3-02 — Implement basic PDF annotation and form editing

**Repository:** document-platform, document-web. **Dependencies:** R3-01.
**Feature IDs:** editor.add_text, editor.highlight, editor.annotate, editor.fill_forms, editor.signature_image, editor.export.

Implement text overlays, highlights, notes/drawings, existing form fields, supplied signature images, undo/redo and export with multilingual fonts and accessible controls.

**Acceptance:** Editing and exported PDF agree on page coordinates/rotation. Signature images are described accurately and not sold as cryptographic digital signatures. Export does not spend again after the quoted edit work.

### R3-03 — Implement genuine existing content and image changes

**Repository:** document-platform, document-web. **Dependencies:** R3-02.
**Feature IDs:** editor.existing_text, editor.insert_images, editor.replace_images.

Implement actual supported text-object edits, font/layout handling, image insertion/replacement/removal and compatibility warnings. Preserve version history and owner constraints.

**Acceptance:** Text extraction reflects the new content; hidden old text is not merely covered. Unsupported fonts/layouts produce clear options. Existing images change in the serialized PDF, not only in the canvas preview.

### R3-04 — Implement verified permanent redaction

**Repository:** document-platform, document-web. **Dependencies:** R3-03.
**Feature IDs:** editor.redact.

Implement Premium redaction marks, explicit finalization, object/image/text sanitization and final output validation with the qualified engine.

**Acceptance:** Redacted material cannot be recovered through text extraction, object streams, embedded images, incremental revisions or preview assets. Failure of these checks blocks the feature from release.

### R3-05 — Implement reusable and batch form filling

**Repository:** document-platform, document-web. **Dependencies:** R3-02.
**Feature IDs:** editor.form_templates, editor.batch_forms.

Create versioned field mappings, typed reusable data, preview, input validation and independently metered batch output with private per-document handling.

**Acceptance:** Missing/ambiguous fields are reported before submission. One recipient record cannot leak into another output. Partial failures charge only valid successful documents.

### R3-06 — Pass final roadmap acceptance and operational handoff

**Repository:** document-platform, document-web. **Dependencies:** R3-03, R3-04, R3-05.
**Feature IDs:** cross-cutting infrastructure / release gate.

Run the complete feature coverage report, cross-channel three-locale journeys, editor accessibility, output recovery tests, analytics reconciliation, restore drill and operational review. Publish release notes and final known limitations.

**Acceptance:** All enabled catalog IDs have real behavior and evidence. Unqualified features stay disabled with explicit blockers. Secrets, contracts, deploy order, rollback, cost controls and incident procedures are documented.

## Required release evidence

- Coverage report: feature ID → ticket → implementation files → verification evidence → enabled state.
- Public/admin schema versions, generated client pin and migration/deployment order.
- Screenshots at mobile/desktop sizes, three-locale output fixtures and documented UI/UX findings.
- Payment/usage/report reconciliation fixtures for any release affecting money or reporting.
- Known limitations, unresolved provider/license decisions, runbooks, restore/rollback notes.
- A concise handoff stating what really works, what remains gated and why.

Do not mark a milestone complete merely because a route, button, prompt, mock API or screenshot exists.
