# PdfCraft bench, 2026-10-31

`pdfcraft-cli` 0.16.1 (macOS universal build), network off, home folder unreadable, page by page. Results checked in three
independent readers (pdfium, pdf.js, Apple PDFKit), with samples reviewed by eye. Counts only: no document text or file
names are recorded, and the real files were deleted after the run.

"Clean" means the new text reads correctly in all three readers, nothing else on the page changed, the text fits, it is
not stretched, and the font is kept or nearly identical.

## Text edits (one word or number)

| PDFs made by | Clean |
|---|---|
| Chrome (Russian, Uzbek, English) | 44 of 48 |
| ReportLab with Noto (our generator) | 13 of 17 |
| ReportLab with Helvetica | 2 of 2 |
| macOS Quartz, Latin | 12 of 12 |
| macOS Quartz, Cyrillic | 2 of 12 (glyphs stretched up to 2x) |
| LibreOffice | 0 of 10 (font lost) |
| Scan with an OCR layer | 0 of 1 (dark blocks painted over the scan) |
| Word, Latin paragraphs | 67 of 76 |
| Word, Cyrillic paragraphs | 3 of 19 (3 files, mostly one) |

For comparison, today's `replace_text` accepted 6 of 197 attempts on the synthetic set, all on Helvetica-only files.

## Traps

- Pass `text_paragraphs.editor_text` with its row breaks to `text_edit`. Flattened text moves titles sideways and clips
  text off the page.
- One letter missing from a subset font can switch a whole run to a Type 3 fallback. Import a full face and apply it with
  `ranges` to the new letters only (about 440 KB per edit).
- PDFs do not reflow, so longer text overlaps what follows. Detect it from `draft_rect` against neighbouring paragraphs;
  the `overflow` flag is noisy.
- `ok` does not mean good: render and check every result. pdfium is not thread-safe, so check in separate processes.

## Redaction

| Test | Result |
|---|---|
| Find a word and remove it | clean in 38 of 40; two left a copy of the word containing a space, one more matched nothing |
| Box over text | text under the box removed in 38 of 38 |
| Box on a lossless scan | only the box area removed |
| Box on a JPEG image or scan | the whole image is deleted (the page goes blank) |
| Box touching a vector panel | the panel is deleted |
| Digitally signed file | edits and redaction refused |

## Speed and stability

Under 0.3 s and 50 MB per edit. Redacting every match in 300 pages: 5 s and 133 MB. 120 corrupted files: no crash or hang
(94 opened, 26 refused cleanly; the run only opened, listed and saved them).
