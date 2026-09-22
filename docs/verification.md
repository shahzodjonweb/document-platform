# Verified local checkpoint · 2026-09-22

## Reproducible checks

| Check | Result |
|---|---|
| `DEBUG=1 .venv/bin/python -m pytest tests -q` | **114 passed** in 31.97 seconds on the final independent integration run. One upstream pypdf deprecation warning from an intentionally malicious JavaScript fixture. |
| `manage.py check` | No issues. |
| `manage.py makemigrations --check --dry-run` | No drift. Core migrations 0001–0004 and operations 0001 applied. |
| `python scripts/verify_contract.py` | Public schema matches generator and checksum; no staff routes. |
| `python scripts/coverage_report.py --check` | All 128 feature IDs map exactly once to the original 48-ticket backlog. No production release approved. |
| `npm run test:browser` in platform | **2 passed**: separate staff login, EN/UZ/RU at 1440/390 px, no body overflow, draft plans/gated payments, automated WCAG 2 A/AA overview audit at both widths. |
| Customer typecheck / build | Passed; see customer `docs/design/QA.md`. |
| Customer browser integration | Real authenticated PDF merge/download, source order, locale switch, reload-preserved draft, exact one-task/three-page settlement, result refresh. |
| Customer independent axe audit | Dashboard and completed result at 390 px: zero detected WCAG 2 A/AA violations after fixes. |
| Live local catalog | 13 genuinely executable tools, including locally qualified DOCX/PPTX conversion. |

## Tests exercise outcomes

- Actual PDF page ordering, dimensions, rotations, compression/no-op, rendered images, AES password roundtrip, and serialized output readability.
- Actual multilingual DOCX/PPTX fixtures converted to three-page PDFs; all six output pages visually inspected. Office preflight and settlement use actual rendered page counts. Concurrent Office jobs have separate profiles.
- Authenticated private previews render real PNG bytes, cache owner-scoped results, enforce expiry/revocation and consume no task allowance.
- Duplicate requests/callbacks settle once; request conflicts reject; failed/no-op jobs restore reservations to original grants; purchased-grant daily-cap exception has invariant tests.
- HMAC tampering/freshness/replay canonicalization, browser challenge binding, cross-account access, CSRF, malformed parameters, malicious PDF/OOXML, short-lived encrypted passwords, crash-orphan cleanup and symlink boundaries.
- Bot offline aiogram tests use real domain work and processor outputs while replacing network transport. This is not evidence of delivery through live Telegram servers.
- Staff customer-realm separation, roles, TOTP replay rejection, login throttling, support audit reasons, test-data exclusion, timezone boundaries, filtered CSV and formula escaping.

## Artifacts

Processor fixtures/evidence live in `processors/fixtures` and `processors/evidence`. Customer screenshots and the downloaded merge artifact live in the customer repository's `docs/design/screenshots` and `tests/fixtures`. Staff screenshot files `docs/design/admin/overview-{en,uz,ru}-{1440,390}.png` were captured through the actual server using development/test records, not fabricated statistics.

Public API checksum at this checkpoint:

`f08ac4118b4b53668af054f913ebcd7bdc544c05b9ed5e55643dffca6baf4583`

The customer repository pins the same public artifact. Staff schema is separate.

## Not established by these checks

Docker/Compose execution, PostgreSQL concurrent-load behavior and restore drills, production Linux parser containment, stable deployed Office licensing/quality, live Telegram iOS/Android/Web continuity/delivery, commercial payment/AI providers, human language/education/legal review and production operational SLOs. The bundled LibreOffice alpha is explicitly development-only. Paid billing and the later AI/education/content-editor roadmap have not been implemented or released.
