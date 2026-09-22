# UI/UX implementation specification

Prepared 2026-09-22. This is an implementation handoff, not a deployed application. Product name is intentionally a configurable placeholder until the owner chooses a brand.

Precedence: user instructions, then `IMPLEMENTATION_PLAN.md`, then `feature_catalog.json` for exact plan access, then this UI/UX detail, then staging examples. This document must not override the master specification's billing, identity, privacy, metric, or release rules.

## 1. Product and repository boundaries

- Repository 1, `document-web`: customer website, authenticated customer app, Telegram Mini App shell, locale catalogs, accessible reusable UI components, and generated API client. The same application serves ordinary browsers and Telegram.
- Repository 2, `document-platform`: Telegram bot, API, workers, admin dashboard, restricted Django admin, payment and entitlement logic, generated contracts, operations, and administration locale catalogs.
- No staff routes, administrative API clients, staff-only query code, or admin bundles in repository 1. Proposed admin implementation is server-rendered Django templates with small focused JavaScript modules. Django admin remains a restricted data-maintenance surface; the custom dashboard is the normal business interface.
- Public modes: General documents, Student, School practice, Teacher. Modes change discovery and templates, not account type or subscription. A teacher can use student tools without creating another account.
- Plans: Free, Plus, Premium. Plus inherits Free; Premium inherits Plus. The server owns feature entitlements, prices, quotas, and eligibility. The UI consumes these values rather than duplicating policy in hard-coded conditionals.
- Release gates: P1 file tools; P2 AI document/presentation and education tools; P3 visual PDF content editing. Public menus show only released capabilities. Future features may appear in an explicitly labeled roadmap, never in the active purchase benefits.
- Suggested visual direction: a calm document workspace using crisp typography, small color accents, real file previews, and compact task cards. Avoid treating the whole service as a chatbot with a single blank prompt.

## 2. Navigation and customer routes

Use an explicit `uz`, `en`, or `ru` URL prefix for customer routes. Example: `/uz/app/jobs/01...`. Route IDs and API slugs remain language-independent. When changing language, preserve the current task, query, and selected files. Landing-page copy is translated independently of interface strings.

| Route after locale prefix | Page | Required content and controls |
|---|---|---|
| `/` | Public landing | Specific file-tool benefits, five active popular tools, short product demo, plan summary, language switch, Start in Telegram and Open web app. No fabricated customer counts or testimonials. |
| `/tools` | Public tool directory | Categories, text search, output format, released features, plan labels. |
| `/tools/:toolSlug` | Public tool page | What it does, input/output examples, limits, upload/open action, concise instructions. |
| `/pricing` | Plan comparison | Free/Plus/Premium, current monthly allowances, Stars price, billing period, exclusions, trial rules, cancellation/refund links. |
| `/help` and `/help/:slug` | Help | Search, processing help, supported formats, payments, deletion and privacy, contact. |
| `/legal/terms`, `/legal/privacy`, `/legal/refunds` | Legal information | Current versions and effective dates. |
| `/auth/telegram` | Browser account entry | First-party Telegram confirmation link/QR, initiating browser/device description, pending/approved/expired states, clear cancel/back controls; no separate password account. |
| `/app` | Dashboard | Drop zone, recent tools, last active mode, remaining allowances, recent jobs, relevant templates. |
| `/app/tools` | Tool library | Searchable categories and supported operations; the five priority P1 tools appear first. |
| `/app/tools/:toolSlug` | Operation workspace | Tool-specific inputs/settings, previews, eligibility, quote, job submission. |
| `/app/jobs` | Recent tasks | Status, tool, created time, retained-file status, filters, reusable parameters. |
| `/app/jobs/:id` | Job detail/result | Current stage, outputs, charge/credit receipt, retry choices, download/send-to-Telegram actions. |
| `/app/create` | AI creation hub, P2 | Document or presentation, source type, active templates, audience. |
| `/app/create/:draftId` | AI creation wizard, P2 | Sources, goals, outline, style, quoted maximum and charging basis, generate, revisions, export. |
| `/app/study` | Student mode, P2 | Summarize, flashcards, practice, PDF questions, exam pack, notes, formatting, revision plan. |
| `/app/school` | School practice, P2 | Grade/subject chooser, explanation, hints, worksheets, reading/vocabulary, project help, saved results. |
| `/app/teach` | Teacher mode, P2 | Lesson pack, worksheets, tests, versions, differentiated material, syllabus planning, rubrics, feedback. |
| `/app/practice/:id` | Interactive practice, P2 | One exercise at a time, submit answer, reviewed explanation, optional follow-up practice. |
| `/app/pdf-chat/:id` | Questions about a document, P2 | Document preview, conversation, page references, no-answer state, remaining credits. |
| `/app/editor/:id` | Visual PDF editor, P3 | Pages, canvas, tools, properties, versions, save/export state. |
| `/app/templates` | Template library, P2 | Previews, filter by purpose/locale, saved preferences, premium distinctions. |
| `/app/workflows` | Saved file workflows | Ordered operations, defaults, input/output compatibility, quote before each run. |
| `/app/billing` | Subscription and usage | Plan, renewal/end date, balances, reset times, transaction history, cancellation, available top-ups. |
| `/app/settings` | Account preferences | UI/output language, timezone, display theme, paper size, notifications, linked Telegram identity. |
| `/app/referrals` | Referral status | Share action initiated by user, qualifying rules, capped rewards, pending/earned status. |
| `/app/support` | Support ticket | Category, optional job/payment reference, concise message, status. |

Navigation patterns:

- Desktop: 224–248 px sidebar; logo, Home, Tools, Create, Education, Recent tasks. Billing and Settings at the bottom. Hide unreleased items.
- Mobile and Mini App: four bottom items: Home, Tools, Tasks, Account. Put Create and Education in the Tools category selector in P2. Limit top-level mobile navigation to four items.
- Public website: lightweight header with Tools, Pricing, Help, language, and primary start action. Customer shell and public shell share tokens but not navigation density.
- The dashboard starts with the user's task, not subscription advertisements. A usage chip opens details; upgrades appear in context.
- Desktop detail pages use a central workspace with a 280–320 px settings/summary rail. Mobile uses a single column with settings sections or a bottom sheet; keep primary action reachable without covering content.

## 3. Telegram bot menus and conversation model

The bot must be usable for the P1 core tools without opening a web app. Visual page ordering, richer previews, multi-step AI review, and the P3 editor may open the Mini App. Every such handoff preserves the same draft/job ID and uploaded files.

Persistent commands:

| Command | Purpose |
|---|---|
| `/start` | Welcome or resume, language shortcut, send-file instruction. |
| `/menu` | Main actions. |
| `/tools` | Categorized tool picker. |
| `/myfiles` | Recent tasks and available results; label clearly as temporary files. |
| `/plan` | Plan, allowances, renewal/end date, upgrade or cancellation. |
| `/language` | O‘zbekcha, English, Русский. |
| `/help` | Examples and processing support. |
| `/support` | Contact product support. |
| `/paysupport` | Purchase/refund support. |
| `/terms` | Purchase terms. |
| `/cancel` | Cancel the current input flow, with the actual job-cancellation result shown separately. |

First start: infer a supported language, display a compact welcome and one-tap language selector, and immediately accept a file. No mandatory name, phone, education role, or payment step. Remember an explicit locale choice over Telegram's inferred language.

Main inline keyboard for P1:

1. PDF tools | Convert files
2. Recent tasks | My plan
3. Open workspace | Help

P2 adds AI documents | Study & teaching. Do not place twenty tools in one message. Categories contain at most 6–8 actions per page, with Back and Cancel. Always label buttons with an action; use emojis sparingly and never as the only label.

Bot input behavior:

- Accept a file before an operation is selected; inspect it and show relevant tools. Accept operation-first and file-first paths.
- When receiving several PDFs or an album, show a collected-file list with explicit Done/Continue. Arrival order is a proposed order, not a silent final choice. Allow removal and renumbering; offer Mini App thumbnails.
- Give a short instruction when image quality may be affected by Telegram photo compression and offer sending as a file; do not block a valid photo input.
- Edit the existing status message as a job progresses instead of sending one message per stage. Send one final result notification. Do not send promotional broadcasts by default.
- Callback buttons contain short opaque server references. Expired callbacks offer Resume task or Start again rather than a cryptic error.
- A new upload during an unfinished task prompts Add to current task / Start new task. The current draft remains recoverable.
- The language switch affects subsequent messages and the current available keyboard; it does not erase the task.
- A blocked bot or missing write permission cannot invalidate a completed web task. Downloads remain accessible in the web app; provide a reconnect action.

## 4. Required journeys and states

### 4.1 Core file operation

1. Receive/select one or more files.
2. Validate format and initial limits; inspect encrypted/corrupt inputs without charging.
3. Present compatible actions or the chosen tool's settings.
4. Preview pages or source order when relevant. Compress shows size/quality tradeoff without claiming a guaranteed percentage saving.
5. Obtain the server quote: accepted file/page counts, effective plan, credits or standard operations, remaining balance, quote expiry, and retention deadline.
6. User starts processing through a verb-specific action such as Merge 3 PDFs, Compress PDF, or Convert to Word.
7. Show real job stages: queued, preparing, processing, finalizing. Only show a numerical percentage when it reflects measurable work. Indeterminate tasks get a stage label.
8. Present result size, output count, relevant warnings, download, Send to Telegram, repeat-with-settings, and retention deadline.

Special states:

- Too large: state actual size/pages and current limit; offer a smaller file, applicable plan, or supported upload path. Avoid an upgrade if the task exceeds every plan's limit.
- Corrupt/unsupported file: explain what failed and suggest a supported input. Keep unaffected files in a multi-file draft.
- Password required: ask for the supplied password only for that processing attempt, mask it in the UI, never put it in chat-history summaries or telemetry. Offer browser entry when appropriate.
- No meaningful compression: retain the original and state that further reduction would reduce quality. A no-op compression is not charged; show that no allowance was consumed.
- Missing font/conversion loss: show a plain-language warning and side-by-side preview when possible. Editable conversion must not be marketed as visually exact for all PDFs.
- Insufficient balance: display required and available amounts, top-up/upgrade choices, and the preserved draft. Return directly to the quote after purchase.
- Quote expired or file changed: refresh quote and request confirmation if the cost changed.
- Failure: say which stage failed, whether credits were restored, whether input remains available, and whether retry is free or needs a new confirmed charge. A support reference is optional detail, not the whole error.
- Partial batch failure: list individual outcomes, download successful outputs, retry failed items, and show the actual settled charge.
- File expired: show task metadata and Re-upload; never imply deleted server content is recoverable. Avoid thumbnails that silently depend on expired sources.

### 4.2 AI document/presentation

Use a four-step wizard: Content → Outline → Style → Generate. The first step chooses Topic, Paste text, or Upload material. Ask only questions that change the output: document type, language, audience, approximate length, and optional supplied sources.

- Outline rows can be renamed, reordered, added, and removed using drag plus keyboard/button alternatives. An outline itself may consume a clearly displayed small allowance; specify this in the quote rather than implying all planning is free.
- A slide preview shows theme, font sizes, page ratio, and sample content. Do not render every slide as a non-editable screenshot if the user selected an editable PPTX.
- Quote identifies document size, image-generation inclusion, revision charging, the quoted upper bound, and the actual settlement basis. The final charge cannot exceed the authorized quote. Separate paid AI work from export/download.
- Results show a thumbnail strip, readable content preview, edited version indicator, PDF/PPTX downloads, and section/slide-specific revision actions. Each revision gets a separate quote when chargeable.
- Canceling a screen is distinct from canceling a running generation. If a submitted task will continue, state it. If cancellation is still possible, show a cancel action that waits for backend acknowledgement.
- Do not add fabricated bibliography entries. An unanswered PDF question gets a clear Not found in this document state; citations open the relevant page.
- Web text input may contain topic, generated text, or source content; these strings must never be interpreted as markup or executable code in previews.

### 4.3 Education

- One mode chooser offers Student, School practice, Teacher; it is skippable and revisitable. Grade and curriculum inputs are user-supplied context. Do not claim alignment to a particular curriculum without the supplied reference and review.
- Student exam pack: upload → select topics and exam date if needed → output checklist → quote → generated outputs. Free gets the catalog's mini sample; the Plus bundle contains summary and questions; Premium adds flashcards and a revision plan. Answer explanations follow the underlying quiz feature. Individual included tools remain available under their normal allowance; do not deny Plus access to standalone flashcards or a revision plan merely because its one-click pack is smaller.
- School help: choose grade/subject → submit a lesson or problem → show hint/attempt/explanation controls → optional similar exercise. Do not require a child's full name, birthdate, school, or contact details for generation.
- Handwriting review: uncertain regions are highlighted and editable before a final clean document is generated.
- Teacher lesson pack: topic/grade/duration/objectives → choose outputs → review outline and question previews → generation → separate student bundle and teacher bundle. The one-click pack is unavailable in Free; Plus gets the plan and worksheet, and Premium adds slides, homework, and teacher key. Independently generated quizzes/tests still include their authorized answer keys across plans.
- Test variants share target skills but must be reviewable. Show version labels and answer-key pairing. A teacher can edit questions, points, and answers before export.
- Saved class settings store level, subject, template, and style; avoid collecting student rosters as a requirement for MVP.
- Suggested marks and feedback are explicitly drafts for teacher review. Approved edits should be preserved in exports.
- Artifact roles are `user_document`, `learner_material`, `teacher_key`, `teacher_feedback`, and `public_preview`. Teacher answer keys are separate files with a separate authorization path, not just another page or a visually hidden section. Default Share student materials accepts learner roles and excludes keys, rubric notes, and private feedback at the API level. Add a preview of exactly which artifacts will be shared through explicit, scoped, revocable, time-bounded links. Recipients receive only that material, not the owner's sources, jobs, billing, or account. No automatic distribution to chats.
- Interactive practice shows only the current question's feedback after submission. Bulk-exported practice may include a separate answer key for the owner, with its label clearly visible.
- Saved study sets and adaptive history require an explicit Save project action. Show what will be saved and the 90-day renewable retention window: approved generated question/answer data and necessary cited excerpts, not the entire uploaded textbook. Deletion and extension controls are visible. Source binaries still expire under the normal file policy.
- Independent child onboarding must pass the platform age-eligibility gate defined in the master specification; adult-assisted generation remains available without a child account or roster.

### 4.4 Subscription and upgrade

- Default all customers to Free; do not ask for a plan before their first useful task.
- At a relevant limit, show the locked capability, the smallest eligible plan, actual 30-day/provider-period allowances, and whether that plan can become active now or only after the current paid period. A larger file that only needs Plus should recommend Plus. A top-up adds usage but cannot unlock a capability excluded from the current plan.
- Plan cards show Free, Plus, Premium side by side on desktop and stacked on mobile. Avoid preselected Premium, fake urgency, crossed-out invented prices, or false popularity labels.
- Preserve input and outline across checkout. A first paid subscription or eligible top-up becomes usable only after server confirmation, then the user can resume under a refreshed quote. Scheduled paid-plan changes do not activate early or unlock the preserved job. Never submit a previously quoted task twice automatically. If input expires before a scheduled change, keep metadata/settings and request re-upload.
- Invoice states follow the master lifecycle: created, presented, pending, paid, canceled, expired, failed. Refunding/refunded are a linked refund lifecycle; subscription pending/active/cancel-at-period-end/expired/revoked are separate. A transient received/activating message may explain server synchronization but cannot grant access from a client success event.
- Billing page separates included standard operations, included AI credits, purchased top-ups, and referral rewards. Included grants expire at the period end; purchased top-ups do not expire in v1; referral grants expire after 30 days. Show the next reset, the actual provider period, and the disclosed Free-cycle/daily reset time in the user's timezone. Never label a 30-day period as a calendar-month boundary.
- Renewal off: show Active until DATE. Do not label cancellation as immediate expiry. Failed renewal: state the actual entitlement end and what happens to new work. Never delete user content as an unannounced consequence of canceling.
- In v1, changes between existing paid plans are scheduled at the current period boundary. Show the effective date, cancel the old renewal with provider confirmation, preserve paid access, and request a newly confirmed checkout for the new plan at expiry. A scheduled choice neither auto-debits a changed amount nor grants the new plan. Do not offer instant paid upgrades or proration without the separate tested billing ADR required by the master.
- Staging plan values are labeled DRAFT; live checkout remains disabled while production Stars prices are null. The browser purchase action opens the same Telegram Stars invoice; a second payment provider is outside v1.
- The product's Premium subscription is labeled Product Premium where necessary, so it is not confused with Telegram Premium.

### 4.5 Shared account and cross-channel continuity

- Telegram user ID maps to one internal user; bot, Mini App, and browser share jobs, allowances, plan, preferences, and billing state.
- Browser login resolves to that same identity through a five-minute, one-use challenge bound to the initiating browser's HTTP-only challenge cookie and verifier. The bot shows the browser/device request and asks the authenticated Telegram sender to approve. The browser displays pending, approved, canceled, or expired status; only that initiating browser can redeem approval. Do not merge accounts by display name, username, phone guess, or email guess.
- Public landing/tool discovery is available without login; processing starts only after a verified session. If a user selected a local file before login, retain it in memory where feasible and explain if a browser restart requires reselection.
- Open in workspace links identify a server-authorized job/draft. Possessing an ID or link alone does not grant access to a private document.
- Device changes resume server-saved drafts whose files still exist. Display Not yet uploaded for locally selected files; never imply an unsent file is already saved.
- Send to Telegram is an explicit per-result action except for tasks originally submitted through the bot, where returning the requested result is expected. If the bot has not been started, offer an identity-bound connect flow.
- Inputs, previews, and output binaries expire by default 24 hours after completed work, equally across plans. Show the exact deadline; expired/revoked files stop being downloadable even while asynchronous deletion finishes. History metadata, explicitly saved education projects, persistent templates/settings/logos, and minimal financial records have distinct disclosed retention rules. A generic history page is not permanent cloud storage.

## 5. Telegram Mini App adapter

Verified Telegram-specific requirements [S1]: validate `initData` on the server; never authorize from `initDataUnsafe`. Read Telegram theme values and react to `themeChanged`. Use `viewportStableHeight` for stable layout; respond to viewport and keyboard changes. Respect device `safeAreaInset` and Telegram `contentSafeAreaInset`, updating them on change. Use the native BackButton and optionally one native bottom action. Feature-detect fullscreen, download, and other optional methods; provide browser fallbacks. Honor a deliberate unsaved-work close confirmation. Native invoice completion still requires server payment confirmation. A Mini App link is not permission to send to any chat.

Product implementation requirements:

- Isolate Telegram SDK interaction in a composable/adapter; components consume capabilities instead of calling global objects throughout the codebase.
- Do not show both a fixed HTML primary button and a Telegram native primary button for the same action. Route-level action controller owns one visible primary action and cleanup on navigation.
- Reserve all inset space once at the shell level; prevent components from double-applying top/bottom padding. Explicitly inspect full-screen screenshots on notched devices.
- Embedded mode suppresses duplicate website marketing navigation and uses compact headers. Ordinary browser mode preserves expected browser navigation.
- Keyboard opening must keep the active field and its validation message visible. Long text entry uses a scrollable content area, not a fixed-height modal.
- Current tasks continue if the app is minimized. Reconnect queries current server state and reconciles its version; it does not replay submission requests.

## 6. Design system

These are proposed visual defaults, not measured brand preferences. Implement tokens in both repositories using the same committed JSON/CSS specification; repository 2 can vendor a versioned token artifact. Do not create a third repository.

| Token group | Light | Dark |
|---|---|---|
| App background | `#F5F7FB` | `#0D1421` |
| Primary surface | `#FFFFFF` | `#151F2F` |
| Secondary surface | `#EDF2F8` | `#1C293D` |
| Main text | `#14213A` | `#EFF4FC` |
| Secondary text | `#536177` | `#AAB8CE` |
| Border | `#DCE3ED` | `#334259` |
| Primary | `#245BDC` | `#91B5FF` |
| Primary button text | `#FFFFFF` | `#101A2D` |
| Success | `#166A45` | `#73D9AC` |
| Warning | `#8A5400` | `#F6CA76` |
| Error | `#B32937` | `#FF9EA8` |

- Measure contrast in final combinations, including Telegram custom themes. Color values are starting tokens, not a substitute for contrast verification.
- Use one font family with complete Latin/Latin Extended/Cyrillic coverage, proposed Noto Sans plus system fallback. Bundle permitted font assets; export/render fonts must also cover Uzbek and Russian. Avoid one-locale font subsets.
- Body 16 px / 1.5; compact metadata 13–14 px; desktop page title 28–32 px; mobile title 22–26 px. Staff tables can use 14 px text with sufficient row height.
- Spacing scale: 4, 8, 12, 16, 24, 32, 48. Cards 12 px radius, fields/buttons 8 px radius, dialogs 16 px radius. Avoid rounded-pills for every control.
- Use consistent outline icons at 20–24 px; text labels accompany primary actions. Category icons distinguish documents, images, study, and teaching without one color per feature.
- Use a 1200–1320 px maximum work area for ordinary tasks; editor/admin analytics can be wider. Main task cards should fit without horizontal scrolling.
- Layout targets: 320/360/390 px mobile, 768 px tablet, 1024 px small desktop, 1440 px desktop. Admin tables may scroll horizontally within their own region with visible column context.
- Motion: subtle 120–180 ms transitions; respect reduced-motion preferences. Skeletons indicate structure without distracting shimmer where motion is reduced.
- Buttons: primary, secondary, text, destructive. Fields: label above input, optional help below, error connected to the field. Error state never uses color alone.

Required reusable components:

`AppShell`, `TelegramShellAdapter`, `LocaleSwitcher`, `ModeSwitcher`, `ToolCard`, `ToolSearch`, `FileDropZone`, `UploadQueue`, `FileRow`, `PageThumbnailGrid`, `PageRangeInput`, `ReorderControls`, `PasswordPrompt`, `ToolSettingsPanel`, `QuoteCard`, `AllowanceMeter`, `PlanBadge`, `UpgradeDialog`, `JobStageTimeline`, `JobResultCard`, `ArtifactList`, `RetentionNotice`, `EmptyState`, `InlineError`, `RetryPanel`, `OutlineEditor`, `TemplatePicker`, `SlidePreview`, `SourceCitation`, `QuestionCard`, `AnswerKeyBadge`, `StudentBundlePreview`, `TeacherBundlePreview`, `ReceiptRow`, `CancelRenewalDialog`, and `FeedbackForm`.

Every interactive component needs default, hover where relevant, focus-visible, disabled with explanation, loading, success, error, and empty states. Disabled premium controls include an accessible reason and plan details rather than an unexplained padlock.

## 7. Accessibility and localization

Target WCAG 2.2 AA [S3]. Set a product touch-target goal of 44 by 44 CSS pixels, including more generous spacing in dense mobile grids. All task operations must be keyboard-operable; moving pages must also work with Move before/after buttons. Provide visible focus, semantic headings, labeled inputs, sufficient text/UI contrast, reduced motion, and recoverable focus after dialogs. Announce job status through a polite live region without reading every progress update. Charts require equivalent data tables and summaries. PDFs shown as canvas need accessible page lists and extraction previews where applicable; never claim the canvas alone is screen-reader accessible.

Locale rules:

- Supported UI locales are `uz`, `en`, `ru`. Uzbek UI uses Latin script. Use professional reviewed translations for user-facing actions, billing, errors, and generated templates; do not mix Russian/English fallback text into a released Uzbek screen.
- Preserve UTF-8 end to end. Test `O‘zbekcha`, `o‘qituvchi`, `g‘oya`, `qo‘shish`, `To‘lov`, `Ҳ` in source files when present, Cyrillic names, mixed-script filenames, curly apostrophes, and right apostrophe variants pasted by users. Search may normalize apostrophe variants for matching, but must not rewrite original filenames/content.
- Use ICU-style messages/plurals with explicit variables. Russian requires its plural forms; do not construct sentences by concatenating translated fragments. Labels must support longer translated strings without shrinking the font.
- Localize UI dates/numbers through standard locale formatting using a user-selected timezone; persist timestamps in UTC. The locale must not silently determine timezone. Show timezone in billing deadlines and admin reports.
- Output language is separate from UI language and defaults to it. Show the output choice prominently before generation. Generated language should remain stable when the user switches interface locale mid-task.
- Plan IDs remain `free`, `plus`, `premium`; display names may retain Free/Plus/Premium with localized explanations. Currency/Stars names and quota units use translation keys.
- Display Telegram payments in Stars. A USD/UZS/RUB estimate, if ever added, must be clearly labeled and sourced; do not hard-code an exchange value.
- UI filenames may be ellipsized visually but provide full accessible names and copy actions. File extensions remain intact. Do not use filenames as HTML or as the only download authorization mechanism.
- Screenshots for acceptance include all three locales and long-content cases, not only English happy paths.

Suggested core labels for translation review:

| Meaning | Uzbek | English | Russian |
|---|---|---|---|
| Upload | Fayl yuklash | Upload file | Загрузить файл |
| Merge | PDF fayllarni birlashtirish | Merge PDFs | Объединить PDF |
| Compress | PDF hajmini kichraytirish | Compress PDF | Сжать PDF |
| Processing | Qayta ishlanmoqda | Processing | Обработка |
| Ready | Tayyor | Ready | Готово |
| Download | Yuklab olish | Download | Скачать |
| Plan | Tarif | Plan | Тариф |
| Credits restored | Kreditlar qaytarildi | Credits restored | Кредиты возвращены |
| Teacher key | O‘qituvchi uchun javoblar | Teacher answer key | Ответы для учителя |

## 8. Admin information architecture — repository 2 only

Admin lives at a separate staff origin or server route such as `admin.example.com`, with a separate staff session realm, MFA, role-aware navigation, and no public indexability. Use Django's existing auth/permission system and explicit business permissions; a hidden navigation item is not authorization. All staff screens, filters, metric explanations, actions, and errors support `uz`, `en`, and `ru`; the staff locale preference is independent of the selected reporting timezone.

| Staff route | Page | Main contents |
|---|---|---|
| `/ops/overview` | Business overview | New users, activated users, active paying users, first-time payers, renewals, Stars collected/refunded, successful tasks, success rate, queue status. |
| `/ops/users` | User explorer | Search internal/Telegram ID, registration date, source, language, plan, active entitlement, last activity, first success/payment. |
| `/ops/users/:id` | User detail | Profile summary, identity, plan lifecycle, allowance ledger, task metadata, payment ledger, support cases, audit history. |
| `/ops/analytics/acquisition` | Acquisition | New accounts, verified/referral source, locale, platform, campaign, start→first successful job funnel. |
| `/ops/analytics/engagement` | Usage and retention | DAU/WAU/MAU definitions, successful-task users, feature use, repeat use, signup cohorts, paid/free splits. |
| `/ops/analytics/revenue` | Payments and subscriptions | Stars cash-flow metrics, current plan counts, first/renewal/top-up payments, churn, conversion, refunds, period comparisons. |
| `/ops/analytics/features` | Feature performance | Attempts, successes, failures, unique users, paid conversion after use, latency, cost/usage by tool and version. |
| `/ops/subscriptions` | Subscription operations | Free/Plus/Premium states, renewal status, expiry dates, scheduled changes, provider references. |
| `/ops/payments` | Payment ledger | Unique charges, invoices, payment kind, Stars amounts, state, refunds, webhook receipt status. |
| `/ops/jobs` | Processing operations | Job stage, tool, user, age, attempt, worker/provider, queue, errors, safe retry/cancel. |
| `/ops/jobs/:id` | Job inspection | Metadata, timeline, sanitized logs, charge reservation/settlement/release, delivery attempts, retention status. |
| `/ops/plans` | Plan and quota versions | Effective dates, entitlements, limits, AI rate cards, draft/publish comparison; historical purchases retain their recorded version. |
| `/ops/templates` | Templates and generation configuration | Locale variants, output previews, draft/review/published versions, model configuration metadata. |
| `/ops/localization` | Locale readiness | Missing keys, untranslated copy, approved strings, last review; no arbitrary executable templates. |
| `/ops/referrals` | Referral programs | Qualified/pending/refused rewards, caps, campaign attribution, abuse signals. |
| `/ops/support` | Support inbox | Queue, priority, job/payment reference, assigned staff member, response history, resolution. |
| `/ops/audit` | Audit trail | Actor, action, target, timestamp, reason, before/after for sensitive changes. |
| `/ops/system` | System health | Queue delay, storage, retention jobs, workers, provider errors, notification failures, data freshness. |
| `/django-admin/` | Restricted data maintenance | Only staff with explicit permissions; no routine direct ledger edits. |

Admin dashboard design:

- 1440 px desktop: left navigation, shared filter bar, 6–8 meaningful KPI cards, two chart rows, then exception/task tables. Avoid a page of 40 competing numbers.
- Shared filters: date range, report timezone, compare period, locale, current/at-event plan as explicitly labeled, bot/browser/Mini App channel, acquisition source, tool, production/test environment. Keep filters in the URL where safe.
- Every card has a label, value, scope/denominator tooltip, period comparison when meaningful, updated-at timestamp, and click-through into a reconciled detail table.
- Charts include new users by day, first-time payers by day, currently paid users over time, plan mix, payment-kind mix, successful tasks by tool, job success rate, and signup/payment cohorts. Do not combine counts and Stars on an unlabeled dual axis.
- Paid users view separates current paid entitlement from ever-paid accounts and from payments in the selected period. Grants/trials/test accounts must be identifiable and excluded from paid counts by default.
- Payment amount uses Stars as the original unit. Show refunds separately and net Stars as a derived measure. Financial estimates, if enabled later, include the assumed reward rate and date and are not called cash received.
- A recurring run-rate sums contractual XTR renewal prices for currently active renewing paid contracts and is labeled per 30 days. Exclude one-time packs, complimentary access, and renewal-off contracts; a separate active-service figure may include cancellation-at-end. Do not count renewed charges as newly acquired paying users.
- Cohort heatmaps have a table alternative. Cells after the observation window show Not yet observable, not 0%.
- Zero means a measured zero. No data, delayed pipeline, disabled tracking, and permission denied have distinct states. Failed analytics queries must not show fake zeros.
- CSV exports retain filter, timezone, generated-at, and metric definitions. Escape spreadsheet formula prefixes; audit exports containing user identifiers.

Operational metric definitions follow section 17.5 of the master specification:

| Metric | UI definition |
|---|---|
| New users | Distinct canonical production accounts created in `[from,to)`; repeat `/start` and cross-channel sessions do not create new users. |
| Activated signup cohort | Cohort accounts with their first succeeded job by account creation plus the stated window; only mature cohorts enter finalized rates. |
| Active users | Distinct users with an accepted task, completed practice, or authenticated study interaction; exclude passive reads and webhook delivery. Successful-task active users are separate. |
| First-time payers | Users whose first successful non-test monetary purchase occurred in the window; retain gross history and separately flag later full refunds. |
| New subscribers | Users whose first successful subscription purchase occurred in the window; separate from pack-only buyers. |
| Current paid subscribers | Distinct accounts with a non-fully-refunded paid subscription period covering the snapshot; exclude complimentary grants. Renewal-off subscriptions remain active until expiry. |
| Ever-paid customers | Distinct accounts with any successful paid history; a separate retained-net variant excludes accounts whose entire purchase history was refunded. |
| Payers in period | Distinct accounts with successful charges in the interval, including renewals and top-ups; not equivalent to first-time payers. |
| Renewal customers | Unique accounts with renewal charges in the interval; show renewal transactions separately. |
| Renewal success rate | Paid renewals for periods due in the cohort / subscriptions scheduled to renew in that due cohort, with a matured observation window. |
| 7/30-day conversion | Mature signup cohort with first paid charge within the chosen window / eligible mature signup cohort. |
| Subscription churn | Accounts paid at period start whose paid access ended without continuation by cutoff / accounts paid at start; newly acquired-and-lost accounts are separate. |
| Cancel intent | Renewal disabled; does not mean the paid entitlement has ended. |
| Gross/net Stars | Successful charge amounts by occurrence time; net period cash-flow subtracts refunds occurring in that same period. |
| Retained cohort revenue | Cohort charges less refunds linked to those charges regardless of refund date; distinct from period cash-flow. |
| ARPPU | Chosen period net Stars / distinct paying accounts in that period; disclose cash-flow basis and handle a zero denominator explicitly. |
| Task success rate | Succeeded atomic jobs / (succeeded + failed atomic jobs); cancellations and no-ops are excluded and shown separately. |
| Batch success | Full/partial/failed parent counts shown separately; parent counts are never added to child throughput. |
| Refund rate | Label transaction-based and Stars-based measures separately with their exact denominator; use matching purchase cohorts when evaluating acquisition quality. |
| Retention Dn | Signup cohort users with meaningful activity in the defined day bucket / mature eligible signup cohort. |
| Cost per successful job | All direct costs in the selected job cohort, including failed attempts, / completed jobs; show the denominator and unallocated costs. |

Staff actions:

- Analyst: view aggregated analytics; no access to private file contents.
- Support: inspect allowed user/job metadata, respond to tickets, view payment status; no unrestricted account impersonation or ledger editing.
- Finance: payment/refund and subscription operations with reasons and audit events.
- Operations: inspect/redrive eligible jobs and manage service incidents; redrive must not silently rebill a user.
- Content manager: translated templates/help text and staged publication; no billing or user-content access by default.
- Administrator: roles, configurations, plan/template publication, exceptional actions under audit.
- Opening document content should be exceptional, permission-gated, and purpose-linked; default dashboards use metadata. Retention applies to staff views as well as customer views.
- Refund, entitlement grant, quota adjustment, mass cancellation, and plan publication screens show a concrete before/after summary and request a reason. These controls belong in admin actions with server-side invariants, not raw record-edit forms.

## 9. Instrumentation linked to UX

Use a documented event contract with event ID, canonical user ID where authenticated, timestamp, locale, channel, release version, feature ID, and plan-at-event. Track counts and metadata, not document contents, prompts, passwords, answer text, source text, or file names as analytics properties.

Required event families: signup; bot start; file upload accepted/rejected; feature viewed; task quoted; submission accepted; task completed/failed/canceled; output downloaded/delivered; limit reached; upgrade viewed; checkout opened/canceled; server-confirmed charge/refund; entitlement activated/expired; renewal changed; first successful task; referral qualified; support opened/resolved. Server lifecycle/payment events are authoritative for billing and business reporting. Browser clicks may diagnose funnels but do not create revenue.

Analytics must support identifying where users abandon upload, preview, outline, quote, checkout, and download. Correlate by job/draft/invoice references. Deduplicate bot update retries, repeated browser clicks, and webhook retries before counting business events.

## 10. Required UI/UX agent workflow and deliverables

The implementation agent must explicitly assign a UI/UX agent before building screens. That agent owns design inventory, interaction decisions, locale layouts, and visual review. Work can continue using approved requirements without blocking on routine design choices.

Stage A — inventory and contracts:

1. Map every released feature ID to its category, plan policy, screen, tool settings, input/output, errors, and analytics events.
2. Confirm API contracts for identity, catalog, quote, upload, jobs, billing, previews, and errors with the backend agent.
3. Write tokens, navigation, component inventory, keyboard behavior, and localization glossary in `docs/design/` of repository 1. Put admin counterparts in repository 2.

Stage B — wireframes:

Produce mobile and desktop wireframes for Home, tool directory, upload/merge, page selection, processing/result, plans/billing, AI outline/result, teacher pack separation, PDF editor, admin overview, user detail, and revenue dashboard. Include at least one empty, error, quota, and payment-pending state. Wireframes may be repo-native HTML or design-tool exports; do not require an unavailable external design service.

Stage C — high-fidelity mockups and interactive prototypes:

- Customer screens: 390 px mobile and 1440 px desktop, light and dark, including Uzbek and Russian examples.
- Mini App: safe-area, native-action, keyboard-open, long file list, and restored-task states.
- Admin: real-shaped fixture data, including a true zero day, long username, canceled-at-period-end subscriber, refund, and delayed analytics.
- Prototypes must let a reviewer complete the core flow with fixtures before backend wiring, but demo data may never ship as live production statistics.

Stage D — implementation and review:

- Build the shared components first, then one complete upload→quote→job→result journey, then remaining tool schemas.
- Connect live entitlements and quotes before exposing upgrade copy. Remove mock pricing/data when wired.
- Document component props, API dependencies, statuses, i18n keys, responsive behavior, and keyboard interactions.
- Record screenshot comparisons and an issue list. Fix clipped Russian labels, missing Uzbek glyphs, hidden buttons, unreadable charts, and ambiguous billing copy before release.
- Each phase ends with a design review against the gates below and a backend state-machine review; screenshots alone cannot validate billing or job behavior.

## 11. Acceptance gates

P1 customer gate:

- A new Uzbek-speaking user can send two PDFs, order them, see their allowance, merge, and receive a usable output through the bot; the same task can open in the Mini App without re-uploading.
- A browser user can authenticate to the same account and see the same plan, balance, and job state without duplicate signup counts.
- Free plan limits are clear before submission. Failed jobs and canceled invoices do not display successful charges or extra deductions.
- Reloading a processing page and tapping Start repeatedly do not produce duplicate jobs or charges.
- Long filenames, 50-page preview grids, empty histories, password-protected files, and partial batch failures are understandable in all three locales.
- Keyboard-only users can reorder pages, choose ranges, confirm processing, and retrieve results.
- At 320 px width and 200% zoom, no main control is lost or hidden under the bottom navigation. Safe areas and keyboard behavior pass real Telegram iOS/Android inspection before production release.

P2 gate:

- A Plus user can generate an editable presentation and download the requested format, with settlement matching the disclosed tariff and not exceeding the quoted upper bound.
- A teacher can edit output selection and share a student bundle without the answer key. The teacher bundle includes the correct key for the selected test version.
- Page-reference answers link to valid source pages; missing evidence has an explicit no-answer state.
- Revisions disclose their cost; multiple clicks do not cause duplicate generations. Handwriting uncertainty is reviewable.

P3 gate:

- Add-text and existing-text editing are visually and functionally distinct. Unsupported existing-text edits provide an honest fallback rather than claiming success.
- Redaction preview identifies the permanent operation; exported output is verified by the processing tests to remove content, not merely cover it.
- Unsaved changes, save in progress, saved draft, export in progress, and failed export each have distinct UI states.

Admin gate:

- The same test user's bot start, Mini App session, and browser session create one user; first purchase and renewal count correctly in separate series.
- Every KPI drills into rows whose counts/amounts reconcile under identical filters. Test accounts and granted entitlements are excluded from paid metrics by default.
- Fully refunded, canceled-at-period-end, expired, reactivated, pack-only, and pending-payment users have correct visible status and cohort behavior.
- Staff without a role cannot load unauthorized routes or data by URL/API request. Audited changes include actor, reason, and before/after.
- Date boundaries, selected timezone, filter persistence, pipeline delay, and incomplete cohorts are labeled correctly.
- Core admin workflows work at 1024 px. Phone admin views support triage; dense financial editing is not advertised as a comfortable phone workflow.

## 12. Primary sources checked

The design recommendations are proposed product decisions. Platform-specific facts were checked on 2026-09-22:

- [S1] Telegram Mini Apps: https://core.telegram.org/bots/webapps — authentication data, theme, viewport, safe areas, native navigation/action capabilities, and feature compatibility.
- [S2] Telegram digital-goods payments: https://core.telegram.org/bots/payments-stars — digital services inside Telegram use Stars (`XTR`); support, `/paysupport`, purchase terms, and successful-payment confirmation. The master specification additionally chooses the same Telegram Stars invoice for the initial browser checkout; a second payment system is outside v1.
- [S3] W3C WCAG 2.2 quick reference: https://www.w3.org/WAI/WCAG22/quickref/ — accessibility reference. The 44 px product touch-target goal is stricter than the AA minimum target-size rule; it is a chosen usability target, not a claim that all AA controls require 44 px.

No popularity ranking, adoption forecast, revenue result, school-curriculum endorsement, or exact conversion accuracy is claimed by this specification.
