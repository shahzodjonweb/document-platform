# ADR 0002: editor lane, pointer quotes and PdfCraft

Status: accepted 2026-11-01. Requirements: `docs/product/editor-ux-brief.md`; design:
`document-web/docs/design/EDITOR_V2_UI_SPEC.md`; engine evidence: `docs/verification/pdfcraft-bench.md`.

## Context

The PDF editor stops autosaving silently, has no working undo, refuses Cyrillic drafts at Review and is
unusable on a phone. Decks can only be changed by a paid AI run that redraws everything. Editing needs
fast free work (inspecting a file, checking a text edit, drawing slide previews) that must not parse
customer files in the API process, must not be a billed job, and must not wait behind AI generation on
the one sequential worker.

## Decisions

- **Free work runs in its own lane.** A new `EditorTask` table and `manage.py runeditor` service, modelled on
  the CV reader: lease, SKIP LOCKED, accounts taking turns, one task at a time, per-account budgets. The
  API only creates rows and serves cached results. Exports stay on the existing worker.
- **Quotes point at a saved draft.** An editor or deck quote stores the draft id, its version and a hash of
  its encrypted content, as generation quotes already do, instead of carrying customer text in Quote and
  Job rows. Commands are loaded and re-validated at quote, submit and execute.
- **One send is one job.** Page changes are commands in the same draft and run in one pipeline: PdfCraft
  stage, pypdf overlays, per-page imaging for what could not be removed in place, page operations last.
  A failed rendered check fails the job, and a failed job costs nothing.
- **One file task per draft, counted once.** Re-sending a draft uses no task. Because that removes the
  only cap on Free, sends per draft and per hour and per-account lane seconds are limited.
- **PdfCraft is a pinned third-party binary inside the existing bounded child.** Fetched at image build from
  a manifest with size and SHA-256, amd64 only. Every result is rendered and checked. Without the binary,
  or when it refuses, today's engine is the fallback and the interface says what still works.
- **Decks are pinned at generation.** Design, seed, deck-wide body size, per-slide variants and photos are
  stored with the draft, so a manual edit redraws only what changed and never calls the model.
- **Previews come from the real file.** Slide PNGs are LibreOffice renders of the real deck, in metric-compatible
  fonts, through one resident soffice in the lane.

## Consequences

- One more service and about 1.5 GB more memory ceiling on the host; measured in the container smoke.
- A third-party binary in the image with no network isolation today; pinning first, an egress allowlist and
  seccomp follow in the hardening step.
- Switching deck measuring to Carlito/Caladea changes the fit of new decks once, in its own change.
- `EditorDocument` commands move to encrypted storage across two releases (dual read and write until the plain
  column is dropped).
