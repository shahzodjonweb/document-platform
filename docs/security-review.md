# Independent local security and correctness review

Review date: 2026-09-22. Scope: `apps/core` identity, HTTP endpoints, catalog policy, owner-scoped assets, quotes, reservations, job settlement, private storage/retention, and processor boundary. Implementation fixes were made by the backend owner; this review owns only the independent integration suite and this record.

This is a local engineering review, not production security signoff. Tests use the real Django API client, database transitions, private temporary storage, bounded processor subprocesses, and actual serialized PDFs. They do not replace provider webhook verification with simulated payment success.

## Findings and verification

| Finding | Impact and evidence | Resolution |
| --- | --- | --- |
| Telegram Mini App replay receipt hashed raw query text | An unchanged valid HMAC could be replayed by reordering query parameters, bypassing the one-use receipt. | Fixed: receipt digest derives from authenticated canonical HMAC. Independent reordered-query API regression passes. |
| Split quote assumed output pages never exceed input | Overlapping split ranges could produce four output pages from two input pages after quoting only two, causing a valid accepted job to fail at settlement. | Fixed: quote reserves max(input, selected output sum) and applies output plan cap. Actual four-page job regression passes. |
| Malformed quote identifiers reached uncaught Django validation | A body containing a non-UUID quote identifier could produce a server error rather than a safe validation response. | Fixed: malformed UUIDs/types return safe 400/404 and create no job or reservation. Five independent API cases pass. |
| Interrupted worker left unregistered private outputs | Lease reaper marked the job failed but a PDF written before artifact registration escaped file-row-based retention indefinitely. | Fixed: attempt-directory removal during reaping and failed-job cleanup. Independent interrupted-worker regression passes. |
| Protected output metadata omitted encryption state | Actual encrypted output was recorded with empty metadata and publicly reported as unencrypted; later known-password unlock incorrectly rejected it. | Fixed: outputs persist accurate kind/MIME/page/encryption metadata. Independent API test verifies ciphertext, actual AES document, metadata, response and handle deletion. |

The reaper regression also caught an introduced management-command import error before delivery; this illustrates why management commands are executed in the suite rather than merely reviewed.

## Verified controls

- Foreign owners cannot quote assets, submit another owner's quote, view/delete another owner's file, inspect jobs, or download artifacts. Opaque IDs never substitute for ownership checks.
- Expired quotes create no reservation. Repeating the same idempotency key and quote returns the same job; changing the quote under that key conflicts. Successful work consumes a task once.
- Corrupting the private test input after reservation causes a safe failed job, restores grants once, and exposes no fixture filename/document data in analytics properties.
- Password/path keys and malformed/nested page settings are rejected before quote persistence. Processor parameters accept no arbitrary filesystem path.
- CSRF protects upload and account deletion, and a valid CSRF token cannot authorize a request with an untrusted Origin.
- Stale/future Telegram initData fails, and authenticated parameter reordering cannot create a second exchange.
- Expired downloads revoke access before physical cleanup; cleanup removes the expired registered file while preserving a live file and an outside-root sentinel.
- File passwords are encrypted in short-lived owner-scoped handles, never quote/job settings or response plaintext. A handle that expires after reservation makes the job fail safely, restores allowances, and is deleted.
- The processor suite separately checks actual PDF ordering/rotation/text, PNG/JPG output, AES roundtrip, corrupt/active/interactive PDF rejection, archive traversal/expansion/macros, pixel limits, and safe child-process errors.

## Remaining production gates and review limits

1. PostgreSQL contention and concurrent claim/reserve/settle behavior have not been stress-tested. Local SQLite tests use Django's configured immediate transactions; they cannot prove PostgreSQL race handling or crash consistency. Unique constraints and transactional account/grant/job locks are present.
2. Processor resource limits and child-environment credential removal are verified locally. A child process is not a filesystem/network sandbox. Non-root no-network Linux containment, mount restrictions, temp-disk/PID/cgroup caps, and exploit fixtures remain a release gate.
3. The local orphan sweep now removes unregistered binaries older than 24 hours while preserving registered/recent files and skipping symlinks; the independent age/registration/outside-target regression passes. Production object-store lifecycle, cleanup scheduling and storage-volume failure behavior still require deployment verification.
4. Front-door request-size, upload duration, aggregate storage and distributed rate limits need deployment verification. Django parses file uploads before domain plan-size validation. Local in-memory throttles do not provide multi-process abuse control.
5. Telegram/browser confirmation, Stars, object storage and provider credentials were not exercised against live services. Production prices remain null and paid checkout is disabled.
6. Secret-key rotation/recovery and production secret storage require deployment validation. Password handles expire after ten minutes and are deleted on settlement/cleanup; run scheduled cleanup in the deployed environment. Dedicated transport receipts/challenges also need operational retention policy.
7. The API blocks deleted accounts from ordinary sessions. Full account-deletion orchestration across queued/running jobs, Telegram delivery and already-delivered messages remains a documented operational requirement.

## Reproduction

From document-platform:

```sh
DEBUG=1 .venv/bin/python -m pytest tests/test_adversarial.py -q
DEBUG=1 .venv/bin/python -m pytest tests/test_platform.py tests/test_processors.py -q
```

The independent suite is `tests/test_adversarial.py`. All generated documents are synthetic temporary fixtures; no customer documents, production credentials or real messages were used. Final independent result: **22 passed**, with all five findings above fixed and verified. Command completed on 2026-09-22 in approximately 3.2 seconds. The backend owner separately maintains the platform baseline and combined suite results.

## Expanded review · 2026-09-23

New regression suites cover commerce, bot delivery, batches, studio provider boundaries, branding/revisions and staff integration configuration. Findings fixed during this implementation:

- Workflow confirmation formerly trusted a client boolean. It now requires a signed, expiring owner/version/input/plan-bound token, persisted execution snapshots and recoverable child idempotency.
- Staff demotion could leave Django's legacy superuser flag active. Role changes now clear that flag and revoke operations sessions. Staff cannot change their own privileges through this action.
- Bot process status could mistake a different project's relative `manage.py runbot` invocation for this runner. Control now requires the held lock, recorded PID and exact absolute project command.
- Malformed staff IDs and oversized support replies produced server errors. They now return controlled validation failures.
- Learner PPTX output inherited private speaker notes. Learner roles now omit them; teacher answer keys remain separate and cannot receive learner share grants.
- Output metadata omitted real form fields/page dimensions, preventing safe re-editing. Successful PDF outputs are inspected again in the bounded child and retain safe geometry/form metadata.
- Provider redirects could forward authorization to another origin. Text, image and vision adapters use fixed API origins and reject redirects; no URL-result fetch fallback exists for generated images.
- Provider payload and output limits now cover schema/instructions plus content, bind the selected model to the quote, validate the exact JSON shape and reject output/count/citation overruns without consuming user credits.
- Brand logos resolve only owner-scoped, unexpired, bounded image assets. Quotes bind the logo fingerprint; rendering rechecks the actual bytes. Remote logo URLs and arbitrary paths are rejected.
- Selected-section revisions fork an owned, version-bound source and reconstruct all unselected sections from the original snapshot. Teacher/school sources cannot be recast into a generic public revision.
- A new outbox field exposed compatibility between old and new running workers during an additive migration. Its default is now database-level, with an old-column INSERT regression. Migration application alone is not a substitute for this check.

Secrets in admin are encrypted, input-only and omitted from template contexts/audit payloads. Local encryption uses a random mode-0600 key outside Git. Production configuration must use a stable managed key and verified backup/restore. Sandbox invoices, payments, grants and periods cannot silently become production entitlements.

This review used synthetic files, local transport and mocked external provider responses. It does not establish live provider quality, legal/educational correctness, production isolation or PostgreSQL load behavior. Final aggregate test totals live in `verification.md`.

Final extended findings: actual input bytes are now verified with bounded regular-file reads against the immutable quote before processors or providers run; changing a valid file without updating its database row cannot silently change the task. Teacher feedback, marks suggestions, rubrics, lesson plans and syllabuses default to private teacher roles. Sharing checks also reject legacy links to previously mislabeled artifacts, and answer-key renderers preserve answers/marks in their private PDF/PPTX output. Outline responses must preserve the exact requested section identities. Corresponding regression cases passed before the combined release-candidate run.
# Converter output compatibility follow-up

Older LibreOffice writes a default initial-page viewer destination into generated PDFs. Normalization is limited to fresh converter output and the exact array `[owned-page-reference /XYZ null null 0]`; it removes that hint and validates all remaining active-content rules before serialization and reinspection. Uploaded-PDF handling and rejection of action dictionaries, JavaScript, launch/remote actions, malformed destinations and additional actions remain unchanged. Twelve regression cases cover this boundary.
