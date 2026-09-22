# ADR 002: Local document engines and release qualification

Status: accepted for local implementation, production qualification pending.
Date: 2026-09-23.

The processing boundary uses pypdf for page operations and AES protection, Pillow for image decoding/orientation, PDFium through pypdfium2 for page rendering, and ReportLab for deterministic image PDF layout. It does not use PyMuPDF or Ghostscript. OCR, editable text/table conversion and constrained visual editing are implemented locally with explicit quality limits; production release qualification remains separate. No commercial SDK license or external provider was purchased.

## Installed engines and notices

Versions below were verified against the installed distributions. The application lockfile is authoritative for runtime versions. This records upstream terms, not legal signoff.

| Engine | Version verified | Declared license | Distribution obligations |
| --- | --- | --- | --- |
| pypdf | 6.19.0 | BSD-3-Clause | Preserve package LICENSE and attribution. |
| Pillow | 12.3.0 | MIT-CMU | Preserve package LICENSE and image-library dependency notices. |
| pypdfium2 | 5.13.0 | Apache-2.0 / BSD-3-Clause | Preserve selected binding license and all shipped PDFium BUILD_LICENSES. Documentation/examples use CC-BY-4.0; no example code was copied. |
| PDFium bundled binary | supplied by pypdfium2 wheel | BSD style plus dependencies | Keep full wheel license directory in runtime image; do not strip dist-info/licenses or BUILD_LICENSES. |
| ReportLab | 5.0.1 | BSD license | Preserve package LICENSE. Image PDF engine embeds no font; test fixture Helvetica is a standard PDF font. ReportLab bundled fonts carry separate notices if used. |
| cryptography | 50.0.1 | Apache-2.0 / BSD-3-Clause | Preserve its installed license and bundled crypto dependency notices. |
| LibreOfficeDev | 26.8.0.0.alpha0, build 2c87e51eeaa2b413ff4ae097b2705eea1995d8e5 | MPL-2.0 plus components | Bundled runtime; local qualification only. Preserve the complete Contents/Resources/LICENSE and LICENSE.html, including component notices. Supported stable production image remains gated. |
| Noto Sans fixture fonts | bundled with LibreOfficeDev | SIL Open Font License 1.1 | Verified in the bundled LICENSE section Noto; preserve font notices when distributing fonts. Synthetic PDF fixtures contain embedded font subsets. |
| Tesseract | 5.5.2 | Apache-2.0 | Installed local binary; bundled official tessdata_fast eng/rus/uzb models with license, fixed commit and SHA-256 manifest. Printed multilingual fixtures pass. |
| pdfplumber / pdfminer.six | 0.11.10 / 20260107 | MIT | Preserve installed package licenses; native PDF table extraction only. |
| python-docx / python-pptx | 1.2.0 / 1.0.2 | MIT | Preserve licenses. Editable native Office package output, not screenshot wrappers. |
| openpyxl | 3.1.5 | MIT | Preserve license. Untrusted table values are literal strings, never formulas. |
| Noto Sans editor font | vendored static font | SIL Open Font License 1.1 | Full OFL.txt stored beside font. Embedded Unicode editor/form appearances. |

Primary references: [pypdf project](https://github.com/py-pdf/pypdf), [pypdf encryption](https://pypdf.readthedocs.io/en/stable/user/encryption-decryption.html), [pypdfium2 licensing](https://pypi.org/project/pypdfium2/), [Pillow security guidance](https://pillow.readthedocs.io/en/stable/handbook/security.html), [ReportLab source](https://hg.reportlab.com/hg-public/reportlab/).

## Honest behavior and safety limits

Compression applies lossless stream compression and duplicate/unreferenced object cleanup; text stays text. If the candidate is not at least 1% smaller, the original bytes are returned with `no_op=true` and `saved_bytes=0`. The domain layer must release the reservation and charge no task/page units. No fixed size reduction is promised.

Generated page operations strip the document Info dictionary and root XMP metadata. This is not a redaction or complete forensic sanitization feature. Safe AcroForms are accepted for inspection and the editor preserves canonical fields with Unicode appearances. Basic page transforms still reject forms to avoid orphaning fields. Signed/XFA forms and password fields remain rejected. Active JavaScript, embedded attachments, automatic actions and executable annotation actions are rejected. Harmless internal/URI links are accepted.

Inputs are signature-sniffed rather than trusted by extension. PNG/JPEG/WebP only; single frame; EXIF orientation applied. Office ZIPs are never blindly extracted: traversal, symlinks, duplicate names, excessive expansion, macros, binary/embedded objects, DTD/entities and external relationships are rejected. Legacy DOC/PPT, macro formats, encrypted Office and externally linked content are unsupported.

Hard engine caps are 200 MiB per file, 512 MiB aggregate input, 1,000 input/output pages, 40 million pixels per image/rendered page, 200 million rendered pixels per job, and 512 MiB outputs. Plan-specific limits are lower and authoritative in the domain layer. One image is one input page. ZIP output is created from generated page basenames only.

## Process boundary and remaining deployment gate

Both inspection and execution run as child processes through `processors.sandbox`. JSON is passed over stdin (including ephemeral password material); password values are never placed in command arguments, environment, manifests or errors. The child returns only safe codes and metadata. The wrapper kills the whole process group on timeout, caps reports and applies POSIX CPU/file/descriptor/core limits; Linux also gets a 2 GiB address-space cap. Each attempt has a new empty private output directory; outputs are reopened before a success manifest.

These local limits are not a filesystem or network sandbox. Production release additionally requires the infrastructure gate: non-root container, read-only runtime, private input/scratch mounts, no network, memory/CPU/PID/temp-disk limits, parser exploit containment fixtures, and scheduled lifecycle cleanup. Local reaper and orphan-file cleanup now remove failed/unregistered private attempt files, with regression coverage. macOS resource testing cannot prove Linux production containment. The LibreOffice subprocess has its own temporary profile, a 60-second timeout, and rejects downloaded/embedded content before conversion. English/Uzbek/Russian document and slide fixtures, actual page preflight, and concurrent-profile isolation pass locally. The bundled alpha engine stays production-gated pending a supported stable image and containment qualification. The processor wrapper removes its dedicated process group on exit as well as timeout, so launcher descendants cannot survive a completed attempt.

The local password API now uses encrypted owner-scoped ten-minute secret handles and deletes them after settlement or expiry. Platform/adversarial tests confirm no plaintext password in quote/job settings, responses or analytics, plus failed/expired reservation restoration. Production key rotation and deployment secret-store operations remain qualification work. No passwords may be stored in job/quote parameters.


## New local editor/conversion evidence

`tests/test_advanced_processors.py` adds 21 serialized-output tests, bringing core+Office+advanced coverage to 58 passing cases. These include multilingual OCR, editable Cyrillic DOCX, formula-safe table XLSX, real text/image mutation, native annotations, visible Unicode forms and destructive raster redaction verified by extraction, pixels and OCR recovery. Existing-text replacement is restricted to ASCII in standard Type1 fonts. Redaction copies only masked pixels into a new PDF and reports loss of text/forms plus retention of original versions. No overlay is marketed as replacement or irreversible removal. `docs/processor-capabilities.md` records the complete command/quality contract; `docs/verification/advanced/` retains inspected examples.

### Structured generation and illustrations

The optional text adapter targets the fixed OpenAI Responses endpoint with strict JSON-schema outputs, `store:false`, no tools, bounded request content and a configured model pinned to each quote. Supporting illustrations use the fixed Images generation endpoint, one 1024×1024 low-quality PNG per confirmed job, and accept only bounded base64 PNG bytes; arbitrary output URLs are never fetched. The image model is a separate optional admin setting. No model name or live-provider success is fabricated when credentials are absent.

Implementation references reviewed on 2026-09-23: [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [Create image API](https://developers.openai.com/api/reference/resources/images/methods/generate). Staging product credits are policy values from the supplied seed, not a claim of provider cost equivalence. Live model quality, access and economics remain deployment qualification work.
