# Processor capability contract

The real engine implementations below have local artifact tests. This is engine evidence, not an R1A/R1B release declaration. API policy and release flags are authoritative, including the optional Office runtime and production containment gates. All 128 catalog IDs remain tracked by the platform catalog; capabilities not listed here do not have a processor.

`inspect_file_sandbox(path, password=None)` verifies private input and returns MIME, bytes, kind, pages, encryption state. Password-protected PDFs without a supplied password return `page_count=null` and `password_required=true`; do not quote unknown pages. `normalize_parameters(feature_id, parameters, input_metadata)` validates only metadata/settings and never opens files. `execute_sandbox(feature_id, input_paths, parameters, output_dir, secret=None)` returns a plain JSON-compatible manifest:

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
| `pdf.images_to_pdf` | `paper_size: "A4"`, `orientation: "auto"`, `margin: 24` | PNG/JPEG/WebP in input order. Paper A4/Letter/original; orientation auto/portrait/landscape; margin 0..72 pt. Original means 72 dpi/pixel size plus margins. EXIF orientation and alpha handling. |
| `pdf.to_images` | `format: "png"`, `dpi: 96`, `pages: "all"` | PNG/JPG; 72..200 dpi. Safe ZIP in selected page order, each page decoded after rendering. |
| `pdf.protect` | `{}` plus separate ephemeral secret | AES-256 using owner-scoped encrypted ten-minute handles; deletion on settlement/expiry is tested. |
| `pdf.unlock_known` | `{}` plus separate ephemeral secret | Uses the supplied password through an encrypted short-lived handle; wrong password fails without disclosure. |
| `convert.word_to_pdf` | `{}` | DOCX through detected LibreOffice; bounded PDF preflight supplies actual page count. Qualified local alpha runtime only. |
| `convert.pptx_to_pdf` | `{}` | PPTX through detected LibreOffice; actual PDF pages are checked. Qualified local alpha runtime only. |

Page selections are one-based `1,3-5` strings or `all`; duplicates, descending/out-of-bound ranges and empty results are rejected. Split output page totals cannot exceed 1,000. Input/output page units equal `max(total input pages, total output pages)`. For no-op compression, the manifest still records processed pages for diagnostics but the domain MUST settle zero user units.

`pdf.compression_preview` and `pdf.image_layout` are support/UI catalog IDs backed by the compress metadata and image-layout parameter schema, not independently billable processing endpoints. `files.no_watermark` is an output policy: no platform watermark is introduced. No overlay is represented as true editing or redaction.

## Evidence and open qualification

Run `DEBUG=1 .venv/bin/python -m pytest tests/test_processors.py tests/test_office_processors.py -q` from document-platform. Last local result: 37 passed (2026-09-22). Fixtures test actual page text/order, dimensions/rotation, selected ranges, compression/no-op exact bytes, pixel colors after image PDF rendering, reopened PNG/JPG ZIP members, corrupt/active documents, traversal/macros/archive bombs/pixel limits, secret non-disclosure and AES roundtrip, and child-process execution. Generated examples can be rendered with PDFium; tests assert pixels as well as PDF structure.

A two-page [merge fixture](../processors/evidence/sample-merged.pdf) and its [first-page render](../processors/evidence/sample-merged.png) are retained as evidence. The Poppler render was visually inspected for complete text, spacing and absence of clipping. It contains only synthetic application test copy.

Still gated: production containment, stable supported Office runtime qualification, OCR rus/uzb models/quality, editable PDF-to-DOCX/XLSX quality/license qualification, and all phase-2/phase-3 engines. Tesseract is detected locally but only English/OCR orientation/serial-number models are available, so OCR is not exposed.

## Office preflight and local qualification

The trusted `PDFMASTER_SOFFICE_BIN` environment setting optionally selects a deployment executable; otherwise detection uses `libreoffice`/`soffice` on PATH and a bounded `--version` probe. No client parameter can select an executable. On this host, the bundled runtime is `LibreOfficeDev 26.8.0.0.alpha0` (build `2c87e51eeaa2b413ff4ae097b2705eea1995d8e5`), explicitly marked `development_only=true`. This alpha build is not qualified for production.

Inspection converts accepted DOCX/PPTX into a temporary private PDF, validates it, records `preflight_kind=libreoffice_pdf` and exact output `page_count`, and deletes all preflight/profile files. Inspection uses a 90-second outer limit; each Office invocation has a 60-second limit. Execution converts the unchanged original again; domain settlement cannot exceed the confirmed maximum. Other Office types, macros, external relationships and embedded objects remain unsupported.

Synthetic sources are retained at `processors/fixtures/office-multilingual.docx` and `.pptx`; each has three pages/slides for English, Uzbek Latin and Russian. Native editable PPTX text/shapes and DOCX paragraphs/table/page breaks were used, with bundled Noto Sans fonts. Actual converted PDFs and all six inspected page renders are under `processors/evidence/office/`. Independent concurrent conversions with separate profiles and real text/page-count checks pass. Password handle confidentiality, ownership, deletion and expiry restoration are additionally verified by the platform/adversarial suites.

The committed DOCX/PPTX files are self-contained synthetic fixtures. The optional `processors/fixtures/build/create-slides.mjs` source used the Codex workspace's artifact-tool package to author editable slide objects; it is not a runtime dependency or a production generation adapter. Normal processor tests consume the committed fixture bytes and need only the locked Python packages plus an available Office binary for the optional conversion tests.
