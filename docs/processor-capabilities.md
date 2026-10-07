# Processor capability contract

The real engine implementations below have local artifact tests. This is engine evidence, not an R1A/R1B release declaration. API policy and release flags are authoritative, including the optional Office runtime and production containment gates. All 128 catalog IDs remain tracked by the platform catalog; capabilities not listed here do not have a processor.

`inspect_file_sandbox(path, password=None)` verifies private input and returns MIME, bytes, kind, pages, encryption state, displayed page_sizes, safe form_fields and image_counts. Password-protected PDFs without a supplied password return `page_count=null` and `password_required=true`; do not quote unknown pages. `normalize_parameters(feature_id, parameters, input_metadata)` validates only metadata/settings and never opens files. `execute_sandbox(feature_id, input_paths, parameters, output_dir, secret=None)` returns a plain JSON-compatible manifest:

```json
{"artifacts":[{"path":"/private/attempt/result.pdf","name":"result.pdf","mime_type":"application/pdf","page_count":3,"size_bytes":2048}],"actual_page_units":3,"no_op":false,"metadata":{"engine_versions":{}}}
```

Paths are internal trusted worker values, never client parameters or public API output. Each execution requires a new empty private directory. Files and archives are reopened before success. `ProcessorError.code` is safe to translate; raw parser exceptions, document data and secrets are suppressed.

| Catalog ID | Parameters (additional keys rejected) | Local behavior |
| --- | --- | --- |
| `pdf.merge` | `{}`; at least two ordered PDFs | One merged PDF, input order preserved. |
| `pdf.compress` | `{}` | Lossless structural compression; savings metadata, original bytes/no charge if <1% reduction. |
| `pdf.split` | `ranges?: ["1-2","3"]` | One PDF per range; defaults to individual pages. |
| `pdf.extract_pages` | `pages: "3,1-2"` | Selected pages in specified order. |
| `pdf.delete_pages` | `pages: "2,4-5"` | Remaining pages; deleting every page rejected. |
| `pdf.reorder` | `order: [3,1,2]` | Exactly one instance of every input page required. |
| `pdf.rotate` | `pages: "all"`, `angle: 90` | Angle 90/180/270 degrees; selected page rotations preserved otherwise. |
| `pdf.images_to_pdf` | `paper_size: "fit"`, `orientation: "auto"`, `margin: 0`, `auto_crop: true`, `enhance_text: true` | PNG/JPEG/WebP in input order. Default document edge detection, perspective correction and shadow/contrast cleanup; each switch can be disabled independently. Fit matches the processed image aspect ratio with an 842 pt long edge and no added border; explicit margins are added around it. Paper fit/A4/Letter/original; orientation auto/portrait/landscape; margin 0..72 pt. Original means 72 dpi/pixel size plus margins. Explicit saved paper, orientation and margin settings remain unchanged. EXIF orientation and alpha handling. |
| `pdf.to_images` | `format: "png"`, `dpi: 96`, `pages: "all"` | PNG/JPG; 72..200 dpi. Safe ZIP in selected page order, each page decoded after rendering. |
| `pdf.protect` | `{}` plus separate ephemeral secret | AES-256 using owner-scoped encrypted ten-minute handles; deletion on settlement/expiry is tested. |
| `pdf.unlock_known` | `{}` plus separate ephemeral secret | Uses the supplied password through an encrypted short-lived handle; wrong password fails without disclosure. |
| `convert.word_to_pdf` | `{}` | DOCX through detected LibreOffice; bounded PDF preflight supplies actual page count. Qualified local alpha runtime only. |
| `convert.pptx_to_pdf` | `{}` | PPTX through detected LibreOffice; actual PDF pages are checked. Qualified local alpha runtime only. |

Page selections are one-based `1,3-5` strings or `all`; duplicates, descending/out-of-bound ranges and empty results are rejected. Split output page totals cannot exceed 1,000. Input/output page units equal `max(total input pages, total output pages)`. For no-op compression, the manifest still records processed pages for diagnostics but the domain MUST settle zero user units.

`pdf.compression_preview` and `pdf.image_layout` are support/UI catalog IDs backed by the compress metadata and image-layout parameter schema, not independently billable processing endpoints. `files.no_watermark` is an output policy: no platform watermark is introduced. No overlay is represented as true editing or redaction.

Images-to-PDF scanning runs locally with OpenCV, without an AI provider or OCR call.
It rectifies only a confident, fully visible paper outline. A clipped written
page can receive masked shadow and color cleanup when coherent paper, observed
boundaries and writing at a clipped edge independently qualify it. Missing
corners are never invented: cropped-page geometry remains a literal source
rectangle. With Auto crop enabled, a separately qualified native paper matte
removes confirmed surrounding background onto a white canvas. Observed paper,
its writing, additional visible paper and uncertain paper boundaries remain protected. The page is
trimmed only around verified empty or removed exterior bands (with
downsampling only when the resulting crop exceeds the 16 MP output ceiling).
Unrelated off-paper text is part of the removed scene when Auto crop is on;
turning it off preserves the entire scene. Uncertain outlines,
competing pages and ordinary photos keep the full image. Already full-frame scans
can receive text enhancement without cropping to an inner table. Enhancement
retains colored ink, and applies only inside a detected page when cropping is off.
Both disabled leaves the existing EXIF/alpha/layout conversion unchanged. Detection
uses a 1280-pixel thumbnail; corrected pages are bounded to 16 MP, while original
inputs retain the existing 40 MP limit. The worker keeps its existing CPU, memory
and timeout limits and uses one numeric processing thread. Uniform matte paper
can be tinted or darker than its desk: independently supported luminance and
material-color edges qualify it, while compact writing and visible-edge checks
still exclude unmarked panels and internal printed frames. Dense forms and
barcodes qualify through coherent matte material and numerous stroke-shaped
glyphs; filled holes in a perforated panel do not count as written evidence.
Exterior words on the connected surrounding matte surface veto an incomplete
proposal, including filled tables on a larger written sheet. Unrelated labels
across a dark background do not veto the page;
ambiguous photos keep their pixels and do not receive whole-photo enhancement.
Faint, gently curved outlines receive a bounded 512-pixel, three-iteration
segmentation fallback when
closed edge contours are unavailable. These proposals still require observed
edges, paper/background contrast and compact writing; initialization borders,
competing sheets cannot supply a rectification. Clipped-page qualification uses
a separate mask initialization after the established complete-page fallback.
Each path has one 512-pixel/three-iteration attempt, executed sequentially (at
most six iterations per image), within the existing worker timeout. Tentative empty
bands are checked against source-resolution writing before removal. Clipped
enhancement estimates per-channel illumination from observed paper and boosts
neutral fine strokes using native local contrast, without binarizing or erasing
colored writing. All native matte and cleanup work tiles stay within one million
pixels. Enhancement-only mode preserves exterior RGB exactly; crop-only mode
preserves observed paper and its writing RGB while replacing confirmed background.
An enclosing proposal
supplies context for independently tracing each physical paper edge. Smooth
boundary curves rectify gentle curl into a rectangle, with correction confined
to the outer 20% so blank-margin curl does not bend straight central table rows.
Compact writing guards reject an inner printed frame or shadow seam that would
discard margin text. Uncertain refinement retains the conservative enclosing
crop. A second material seam requires its own local transition, so an already
removed desk cannot justify following a printed frame inward. Reduced-resolution
photos can use lower-degree gentle curves only with the same edge-support and
displacement bounds. Qualified visible corners constrain only unsupported curve
tails that extrapolate outside the pose; additional writing guards veto any lost
marks. Geometry stays within 1280 pixels; inverse geometry samples original RGB
once in strips of at most one million pixels, averaging opposing edge lengths
while enforcing the exact 16 MP output ceiling. Detection is conservative
and may leave low-contrast, obscured or blank pages untouched. Writing-like marks
are required to avoid cropping bright panels in ordinary photographs. Internal `image_processing`
metadata contains only per-page outcome booleans and counts, without document text.
`tests/test_image_scanning.py`, `tests/test_image_scanning_realistic.py`,
`tests/test_image_scanning_safety.py`, `tests/test_image_scanning_rectification.py`,
`tests/test_image_scanning_tinted.py`,
`tests/test_image_scanning_material_safety.py`,
`tests/test_image_scanning_occluded.py`,
`tests/test_image_scanning_dense_safety.py`,
`tests/test_image_scanning_resolution.py`,
`tests/test_image_scanning_partial.py`,
`tests/test_page_rectification_bounds.py`, `tests/test_page_rectification_endpoints.py`,
`tests/test_image_scanning_api.py` and
`tests/test_bot_image_scanning.py` cover artifacts, quotes, jobs and bot switches.
Service verification also processes anonymized clipped, curved gray, tinted and dense
shaded paper through the
actual HTTP/queue/worker/download path and checks the resulting PDF pixels with
defaults enabled, cropping alone and both effects disabled. The checks require
a fitted borderless PDF canvas, physical desk removal and all corner/side writing.
Clipped-page checks require an exact source crop rectangle, preservation of all
visible paper and writing, verified white exterior canvas when cropping is on,
untouched exterior when cropping is off and measurable paper/text cleanup.
Previously generated PDFs are
immutable; scanning changes apply to new image conversions.

## Evidence and open qualification

Run `DEBUG=1 .venv/bin/python -m pytest tests/test_processors.py tests/test_office_processors.py tests/test_advanced_processors.py -q` from document-platform. Last local result: 58 passed (2026-09-23). Fixtures test actual page text/order, dimensions/rotation, selected ranges, compression/no-op exact bytes, pixel colors after image PDF rendering, reopened PNG/JPG ZIP members, corrupt/active documents, traversal/macros/archive bombs/pixel limits, secret non-disclosure and AES roundtrip, and child-process execution. Generated examples can be rendered with PDFium; tests assert pixels as well as PDF structure.

A two-page [merge fixture](../processors/evidence/sample-merged.pdf) and its [first-page render](../processors/evidence/sample-merged.png) are retained as evidence. The Poppler render was visually inspected for complete text, spacing and absence of clipping. It contains only synthetic application test copy.

Production containment and supported stable Office qualification remain gated. OCR, editable text/table conversion and visual editor operations now have local artifact evidence and truthful quality limits below; API policy remains authoritative.

## Office preflight and local qualification

The trusted `PDFMASTER_SOFFICE_BIN` environment setting optionally selects a deployment executable; otherwise detection uses `libreoffice`/`soffice` on PATH and a bounded `--version` probe. No client parameter can select an executable. On this host, the bundled runtime is `LibreOfficeDev 26.8.0.0.alpha0` (build `2c87e51eeaa2b413ff4ae097b2705eea1995d8e5`), explicitly marked `development_only=true`. This alpha build is not qualified for production.

Inspection converts accepted DOCX/PPTX into a temporary private PDF, validates it, records `preflight_kind=libreoffice_pdf` and exact output `page_count`, and deletes all preflight/profile files. Inspection uses a 90-second outer limit; each Office invocation has a 60-second limit. Execution converts the unchanged original again; domain settlement cannot exceed the confirmed maximum. Other Office types, macros, external relationships and embedded objects remain unsupported.

Synthetic sources are retained at `processors/fixtures/office-multilingual.docx` and `.pptx`; each has three pages/slides for English, Uzbek Latin and Russian. Native editable PPTX text/shapes and DOCX paragraphs/table/page breaks were used, with bundled Noto Sans fonts. Actual converted PDFs and all six inspected page renders are under `processors/evidence/office/`. Independent concurrent conversions with separate profiles and real text/page-count checks pass. Password handle confidentiality, ownership, deletion and expiry restoration are additionally verified by the platform/adversarial suites.

The committed DOCX/PPTX files are self-contained synthetic fixtures. The optional `processors/fixtures/build/create-slides.mjs` source used the Codex workspace's artifact-tool package to author editable slide objects; it is not a runtime dependency or a production generation adapter. Normal processor tests consume the committed fixture bytes and need only the locked Python packages plus an available Office binary for the optional conversion tests.

## OCR and editable conversions

The following engines are implemented locally. OCR uses installed Tesseract 5.5.2 and vendored official Apache-2.0 tessdata_fast English, Russian and Uzbek models at commit `87416418657359cb625c412a48b6e1d6d41c29bd`. Source URLs, full SHA-256 checksums and byte sizes are in `processors/assets/tessdata/manifest.json`; only trusted deployment configuration may choose the executable. Printed text is qualified; handwriting and arbitrary source quality are not promised.

| Catalog ID | Parameters | Output and limitations |
| --- | --- | --- |
| `ocr.extract_text` | `language="eng"`, `pages="all"`, `dpi=200` | Actual recognized UTF-8 text. Languages eng/rus/uzb/eng+rus/eng+uzb/eng+rus+uzb; 150..300 dpi. Empty recognition fails without success settlement. |
| `ocr.searchable_pdf` | same | Actual raster PDF with Tesseract searchable text layer; reopens and validates every generated page. |
| `convert.pdf_to_docx` | `mode="text"`, `language="eng"`, `pages="all"` | Native text becomes editable paragraphs; explicit `mode="ocr"` for scans. Reflowed layout, no claim of source layout reproduction. Cyrillic paragraph roundtrip is tested. |
| `convert.pdf_to_xlsx` | `strategy="lines"`, `pages="all"` | Native PDF tables via pdfplumber; `strategy="text"` also supported. Each table gets a worksheet, cells are literal strings to prevent spreadsheet formula injection. Scan/table-structure recognition is not implied. No detected tables fails explicitly. |

Local tests check English, Russian and Uzbek OCR phrases, real searchable text plus page image, editable Cyrillic DOCX without screenshot substitution, and XLSX cells including formula-looking values reopened as strings. The long-term quality dataset and handwriting remain open qualification work.

## Editor command contract

All editor requests use `{commands:[...], accept_rasterization:false}` with at most 100 commands. Coordinates are PDF points from the **displayed top-left**; page indices start at 1. `page_sizes` metadata supplies displayed width/height. Cropped/nonzero-origin page geometry currently fails explicitly; ordinary rotations are normalized. Additional input images are ordered after the source PDF at `input_index` 1 and higher; existing page `image_index` starts at 0. There are no client filesystem paths or executable settings.

| Catalog ID | Command types and main fields |
| --- | --- |
| `editor.visual` | Composes the supported commands below. Domain must authorize each `COMMAND_FEATURES` mapping, not just the visual-editor shell. |
| `editor.add_text` | `add_text`: page,x,y,text,font_size=16,color="#000000". Unicode Noto Sans embedded. |
| `editor.highlight` | `highlight`: page,x,y,width,height,color="#FFFF00". Native PDF highlight annotation. |
| `editor.annotate` | `note`: page,x,y,text; `draw`: page,points=[[x,y],...],color,stroke_width=2. |
| `editor.fill_forms` | `fill_form`: field,value. Keeps canonical editable AcroForm values with embedded Unicode text appearances; signed/XFA/password fields rejected. |
| `editor.signature_image` | `signature`: page,x,y,width,height,input_index. Visible image placement, no cryptographic signature claim. |
| `editor.insert_images` | `insert_image`: page,x,y,width,height,input_index. |
| `editor.existing_text` | `replace_text`: page,find,replacement. Actually mutates text operators; current support is ASCII text using standard Type1 Helvetica/Times/Courier. Complex subset encodings and Unicode replacement fail explicitly. |
| `editor.replace_images` | `replace_image`: page,image_index,input_index; `remove_image`: page,image_index. Mutates/removes real image XObjects; unsupported nested removals fail explicitly. |
| `editor.redact` | `redact`: page,x,y,width,height. Requires `accept_rasterization=true`, cannot be mixed with other edits in one export. |

Redaction rasterizes **every page** at 144 dpi, blacks out rectangles with a one-pixel edge expansion and creates a new PDF exclusively from the masked pixels. It copies no original content streams, forms, annotations, metadata trees or attachments. Reopened validation proves no recoverable PDF text/form tree; the fixture also reruns OCR and verifies the removed secret is absent while public text remains. This permanently sanitizes the exported PDF, while source uploads and earlier versions may still exist until explicitly deleted or retention expires. Every output reports that distinction. Rasterization loses editable text and forms; it is not hidden behind an overlay.

Visually inspected synthetic examples are in `docs/verification/advanced/`: `edited.png` shows real NEW text, English/Uzbek/Russian addition, highlight, note, filled Unicode form and drawn path; `redacted.png` shows the removed secret and visible remaining field content; output PDFs and a searchable OCR example are retained alongside the source. Reproduce with `.venv/bin/python processors/fixtures/build/advanced-evidence.py`.

## Handwritten-note provider boundary and generated layouts

`study.handwriting` now takes exactly one owned PNG/JPEG or one-page unencrypted
PDF. A bounded child produces a JPEG no larger than 1536 × 1536. The configured
vision-capable Responses model receives the image only after a confirmed quote;
local authoring does not claim handwriting recognition. Recognized model families
use conservative image-token bounds from the [official vision documentation](https://developers.openai.com/api/docs/guides/images-vision)
(checked 2026-09-23), added to the complete text/schema byte bound. Unknown model
families require explicit qualification instead of guessing their image cost.
The response must be a bounded transcription with explicit `[unclear]` markers
where uncertainty is declared; the resulting draft is editable and always carries
a human-review warning. Protocol tests use mocked provider responses with actual
rasterized inputs. Handwriting accuracy, language quality and provider cost have
not been evaluated against a live model.

Published paid presets `executive_report`, `compact_brief`, and `study_notes`
change real margins, typography, line spacing and page/slide decoration. The
server enforces `template.professional` eligibility. Generated PPTX removes the
unused binary printer-settings part inherited from python-pptx's template, so
reupload and Office conversion preserve the strict binary/active-content policy.
A real generated-PPTX → upload → PDF conversion test verifies multilingual text.

Synthetic multilingual lesson-pack evidence is in `docs/verification/packs/`:
English, Uzbek and Russian worksheet, private answer key, lesson plan, native
editable PPTX, LibreOffice-rendered slide PDF and inspected page PNGs. These show
provided text and questions; they are not provider-generated teaching material.
The five composite pack operations enforce named material slots and private
teacher-key roles. Local variants shuffle supplied items/options, differentiated
materials apply explicit scaffolding to supplied questions, and weekly packs
partition supplied questions; local mode does not invent a curriculum or infer
question difficulty. Live pack content still requires teacher review.


After a successful handwriting job, the server records encrypted source provenance.
Saving reviewed content/outline for that unchanged source marks the draft reviewed.
The next ordinary quote becomes a zero-AI-credit export of the saved text and never
calls the provider; changing the source clears this state. Public read-only booleans
`transcription_ready` and `transcription_reviewed` describe the state, and clients
cannot set the private provenance marker. Vision rasters are padded to a square
without cropping so extreme aspect ratios stay within the image-token bound.

Study flashcards render paired questions/answers and explanations; study answer
keys render answers, explanations and marks with a private user-document role.
Teacher answer keys retain a private teacher-key role. Teacher feedback, suggested
marks, rubrics, lesson plans and syllabi remain private, including when older
artifacts were mislabeled or already shared. Quote and settlement use one metering
helper: flashcards cost the configured per-started-ten-card tariff, and PDF Q&A
includes the configured base credit charge. Source/page labels are localized.
