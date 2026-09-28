# AI token efficiency and accounting

Document and slide generation keeps the configured model, final output budgets,
source material, citations, and final slide notes. Calls still contain at most
eight sections. The optimization changes how work is requested and recovered.

- Outlines use a dedicated coverage-only prompt and schema. They no longer ask
  for final prose, questions or speaker notes that the outline renderer discards.
- JSON is compacted without changing whitespace inside customer text. Rendering
  metadata stays out of model input. An exact, server-fingerprinted source copy
  can be omitted from a seeded section when the original source remains present.
  Authored or legacy section text is preserved.
- Optional page/slide selection on a finished job limits the requested revision.
  Full document context remains available. The server merges exactly the selected
  IDs and preserves other sections, title and questions. Whole-document revision
  remains the default.
- Failed jobs offer **Review & retry** in web and Telegram. This creates a new
  quote and requires normal confirmation. Valid completed provider batches can
  be recovered from encrypted checkpoints for up to 24 hours, bounded by draft
  expiry. Changes to the draft, sources, prompt, model or schema prevent reuse.
  A fresh generation is a separate intent and does not share this recovery cache.
- Stable instructions precede variable inputs. An opaque account-scoped
  `prompt_cache_key` helps provider prefix caching. This can reduce billed input
  cost and latency; it does not remove the input tokens or guarantee a cache hit.

## Usage report

Staff with Administrator, Analyst, Operations or Finance access can open
**Analytics → AI usage** (`/ops/analytics/ai-usage`). The report stores no prompts,
document bodies or source excerpts. It records actual provider attempts,
including rejected or incomplete responses, and counts replayed response IDs
once. It distinguishes missing counts from zero, and separates input, output,
cached input, cache-write input and reasoning output. The latter three are
subsets, not extra tokens to add to totals.

Usage metadata survives job deletion and expires after 90 days through the
normal cleanup worker. No earlier calls are backfilled. The legacy per-job
`ProviderUsage` records remain for compatibility; use the new `ProviderAttempt`
report for token accounting, especially on failed or recovered jobs.

## Validation and limits

Offline tests cover strict response contracts, source preservation, revision
scope, account isolation, expiry, idempotent retries, partial-batch recovery,
unknown usage, and rejected responses. They do not prove model quality or actual
provider savings. Smaller outline output limits are ceilings, not measured token
consumption. Selecting a small revision can increase input for a single call
because full context is retained, while substantially reducing generated output.

No model downgrade, source truncation, final-document shortening or delayed
batch processing is enabled by these changes. Compare real usage and review
generated EN/UZ/RU documents before making those additional tradeoffs.
