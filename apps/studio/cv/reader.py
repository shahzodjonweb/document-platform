"""The bounded child that reads one of a CV's source files. Run by extraction.read_cv, never imported for use.

A CV can be made from the customer's old CV (a PDF, a Word file, photos or
a scan) or from their LinkedIn profile saved as a PDF or photographed as
screenshots. This program reads one such file and prints its text as JSON:
one entry a page, in reading order, with whether OCR read it, and the
largest lines at the top of its first page, which on a CV or a LinkedIn
export are the person's name.

It runs as its own process with its own limits (CPU, file size, address
space; extraction.py adds a wall-clock timeout and kills its whole process
group), because the file is the customer's and the parsers are large. It
imports nothing of the app and writes nothing: tesseract reads the page
image from stdin and answers on stdout.

Usage: reader.py KIND PATH TESSERACT TESSDATA OCR_PAGES SECONDS
"""
import io
import json
import math
import re
import subprocess
import sys
import time

# Each page's text, at most; a CV page holds about 4,000 characters.
PAGE_CHARS = 12000
# Pages read from one file: more than any CV has, fewer than would cost the request.
MAX_PAGES = 30
# A PDF page is read column by column (pdfplumber) only when that is cheap.
# pdfplumber reads every character of a page before any of its text: a page
# with more text than this in it is no CV page (three or four times one), and
# is read by pypdf instead, which takes a tenth of the time. So are the pages
# after the first LAYOUT_PAGES, which are read in plain order, and every page
# once pdfplumber has had LAYOUT_SECONDS for the file. A small file of dense
# pages would otherwise hold the request that reads it for over a minute.
DENSE_CHARS = 15000
LAYOUT_PAGES = 6
LAYOUT_SECONDS = 20
# A page with fewer letters than this in its text layer is a scan: it is read by OCR.
SCANNED = 20
# One OCR run, at most; a CV page takes a second or two.
OCR_SECONDS = 25
# The pixels a page image is held to before OCR, and the long side a small
# screenshot is brought up to, so its letters are tall enough to read.
OCR_PIXELS = 10_000_000
OCR_SIDE = 2000
OCR_DPI = 200
LANGUAGES = 'eng+rus+uzb'
# Name candidates: the lines in the largest type at the top of the first page.
NAMES = 3
NAME_CHARS = 80
# What a LinkedIn export prints on every page, and nothing of the person's.
FOOTER = re.compile(r'^\s*(?:page\s+\d+\s+of\s+\d+|страница\s+\d+\s+из\s+\d+)\s*$', re.IGNORECASE)


def limits(seconds):
    """CPU, file size, open files and, on Linux, address space: inherited by tesseract too."""
    import os
    import resource
    caps = [(resource.RLIMIT_CPU, (seconds, seconds + 5)), (resource.RLIMIT_FSIZE, (2 * 1024 * 1024,) * 2),
            (resource.RLIMIT_NOFILE, (128, 128)), (resource.RLIMIT_CORE, (0, 0))]
    if sys.platform.startswith('linux'):
        caps.append((resource.RLIMIT_AS, (2048 * 1024 * 1024,) * 2))
    for name, value in caps:
        try:
            resource.setrlimit(name, value)
        except (ValueError, OSError):
            pass
    # Short of memory, the kernel ends this reading (and the tesseract it
    # starts, which inherits this) before the process that asked for it: in
    # the bot's container that is the bot itself.
    if sys.platform.startswith('linux'):
        try:
            with open('/proc/self/oom_score_adj', 'w') as score:
                score.write('1000')
        except OSError:
            pass
    os.umask(0o077)


def tidy(text):
    """A page's text with page footers, stray spaces and runs of blank lines taken out, held to PAGE_CHARS.

    A glyph its font gives no letter for comes out as "(cid:72)": it is taken
    out too, so a page of nothing else counts as a scan and is read by OCR.
    """
    text = re.sub(r'\(cid:\d+\)', '', str(text or ''))
    lines = [' '.join(line.replace('\x00', '').split()) for line in text.splitlines()]
    lines = [line for line in lines if not FOOTER.match(line)]
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()[:PAGE_CHARS]


# --- PDF ----------------------------------------------------------------------------

def _lines(words, tolerance=2.0):
    """`words` grouped into lines by their top, top to bottom: [(top, [word, …]), …]."""
    lines = []
    for word in sorted(words, key=lambda w: (w['top'], w['x0'])):
        if lines and abs(word['top'] - lines[-1][0]) <= tolerance:
            lines[-1][1].append(word)
        else:
            lines.append((word['top'], [word]))
    return lines


def _chars(words):
    return sum(len(w['text']) for w in words)


BOLD = re.compile(r'bold|black|heavy|semibold|demi', re.IGNORECASE)


def _heading(line, usual):
    """Whether a line is set as a heading: in bold, or in type larger than most of its side's."""
    return (any(BOLD.search(str(w.get('fontname') or '')) for w in line)
            or max(float(w.get('size') or 0) for w in line) >= usual + 1)


def _columns(words, x):
    """Whether the gap at `x` parts two columns of text, not a line's words from its dates.

    Each side has three lines and a tenth of the text at least. A date or a
    place set to the right of a role ("Analyst, Example Bank … 2019 – 2022"),
    or to its left as a timeline sets it ("2019 – 2022   Analyst, Example
    Bank"), leaves a gap too, but every line on that side shares its baseline
    with one on the other; a sidebar's lines (Contact, Skills, a LinkedIn
    export's Top Skills) run to their own spacing. A timeline's headings
    (Experience, Education) stand on the dates' side with nothing beside
    them, as a sidebar's do: a line in bold or larger type with no line
    beside it is a heading, and is not counted either way.
    """
    left = [w for w in words if w['x1'] <= x]
    right = [w for w in words if w['x0'] >= x]
    total = _chars(words) or 1
    sides = [_lines(left), _lines(right)]
    if any(len(lines) < 3 for lines in sides) or min(_chars(left), _chars(right)) < total * 0.1:
        return False
    small, other = sorted(sides, key=lambda lines: sum(_chars(line) for _, line in lines))
    tops = [top for top, _ in other]
    paired = [(line, any(abs(top - known) <= 2.0 for known in tops)) for top, line in small]
    sizes = sorted(max(float(w.get('size') or 0) for w in line) for line, _ in paired)
    usual = sizes[len(sizes) // 2]
    counted = [beside for line, beside in paired if beside or not _heading(line, usual)]
    if len(counted) < 3:
        counted = [beside for _, beside in paired]
    return sum(counted) < 0.75 * len(counted)


def _gaps(words, left, right):
    """The runs of x no word covers, widest first: (start, end)."""
    width = int(math.ceil(right - left)) + 2
    cover = [0] * (width + 1)
    for word in words:
        start = max(0, int(math.floor(word['x0'] - left)))
        end = min(width, int(math.ceil(word['x1'] - left)))
        cover[start] += 1
        cover[end] -= 1
    runs, depth, start = [], 0, None
    low, high = 0.12 * (right - left), 0.88 * (right - left)
    for x in range(width):
        depth += cover[x]
        if depth == 0 and low <= x <= high:
            start = x if start is None else start
        elif start is not None:
            runs.append((start + left, x + left))
            start = None
    if start is not None:
        runs.append((start + left, high + left))
    return sorted((run for run in runs if run[1] - run[0] >= 8), key=lambda run: run[0] - run[1])


def gutter(words, box):
    """(top, x, bottom) of the gap between a page's two columns, or None when it has one column.

    Looked for over the whole page first, then below a header and above a
    footer that run across it (a name printed over both columns, a centred
    page number): those are read on their own, before and after the columns.
    """
    if len(words) < 12:
        return None
    left, page_top, right, page_bottom = box
    first, last = min(w['top'] for w in words), max(w['bottom'] for w in words)
    height = last - first
    for head, foot in ((first, last), (first + 0.25 * height, last - 0.08 * height)):
        body = [w for w in words if w['top'] >= head and w['bottom'] <= foot]
        for start, end in _gaps(body, left, right):
            x = (start + end) / 2
            across = [w for w in words if w['x0'] < x < w['x1']]
            if any(head <= w['top'] <= foot for w in across):
                continue
            top = max([page_top] + [w['bottom'] + 0.5 for w in across if w['top'] < head])
            bottom = min([page_bottom] + [w['top'] - 0.5 for w in across if w['top'] > foot])
            inside = [w for w in words if w['top'] >= top and w['bottom'] <= bottom]
            if top < bottom and _columns(inside, x):
                return top, x, bottom
    return None


def page_text(page):
    """A PDF page's text, each column whole and in reading order: header, left, right, footer."""
    words = page.extract_words(use_text_flow=False, extra_attrs=['size', 'fontname'])
    box = tuple(float(v) for v in page.bbox)
    split = gutter(words, box)
    if not split:
        return page.extract_text() or ''
    top, x, bottom = split
    left, page_top, right, page_bottom = box
    parts = []
    for area in ((left, page_top, right, top), (left, top, x, bottom), (x, top, right, bottom),
                 (left, bottom, right, page_bottom)):
        if area[1] < area[3] and area[0] < area[2]:
            parts.append(page.within_bbox(area).extract_text() or '')
    return '\n\n'.join(part for part in parts if part.strip())


def biggest(page):
    """The lines in the largest type on a page, largest first, when they stand out from its text."""
    words = page.extract_words(use_text_flow=False, extra_attrs=['size'])
    if not words:
        return []
    sizes = sorted(w['size'] for w in words)
    usual = sizes[len(sizes) // 2]
    lines = []
    for top, line in _lines(words):
        size = max(w['size'] for w in line)
        text = ' '.join(w['text'] for w in sorted(line, key=lambda w: w['x0']) if w['size'] >= size - 0.5)
        if size >= usual * 1.3 and len(text) <= NAME_CHARS:
            lines.append((size, top, text))
    return named(lines)


def named(lines):
    """Up to NAMES candidates from (size, top, text) lines: the largest first, and a name set on two lines joined."""
    if not lines:
        return []
    top_size = max(size for size, _, _ in lines)
    largest = sorted((line for line in lines if line[0] >= top_size * 0.95), key=lambda line: line[1])
    found = []
    if len(largest) >= 2 and len(largest[0][2]) + len(largest[1][2]) < NAME_CHARS:
        found.append(f'{largest[0][2]} {largest[1][2]}')
    found.extend(text for _, _, text in sorted(lines, key=lambda line: (-line[0], line[1])))
    unique = []
    for text in found:
        if text not in unique:
            unique.append(text)
    return unique[:NAMES]


def render(document, index):
    """One PDF page as a greyscale PNG for OCR, at OCR_DPI or fewer pixels."""
    page = document[index]
    try:
        width, height = page.get_size()
        scale = min(OCR_DPI / 72, math.sqrt(OCR_PIXELS / max(1.0, width * height)))
        bitmap = page.render(scale=scale)
        try:
            picture = bitmap.to_pil().convert('L')
        finally:
            bitmap.close()
    finally:
        page.close()
    return _png(picture)


def quick_text(path):
    """Each page's text as pypdf reads it, in plain order and quickly: None for a page it cannot read."""
    from pypdf import PdfReader
    reader = PdfReader(path)
    texts = []
    for page in reader.pages[:MAX_PAGES]:
        try:
            texts.append(page.extract_text() or '')
        except Exception:
            texts.append(None)
    return texts


def read_pdf(path, ocr):
    """Pages of text from a PDF: pdfplumber's columns, pypdf where it fails or would be slow, OCR where there is no text."""
    try:
        quick = quick_text(path)
    except Exception:
        quick = []
    pages, names = [], []
    started = time.monotonic()
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            for number, page in enumerate(pdf.pages[:MAX_PAGES], 1):
                known = quick[number - 1] if number <= len(quick) else None
                # Dense, or past pdfplumber's time: pypdf's text, read already.
                if known is not None and (len(known) > DENSE_CHARS or time.monotonic() - started > LAYOUT_SECONDS):
                    pages.append([number, known])
                    continue
                try:
                    pages.append([number, page_text(page) if number <= LAYOUT_PAGES else page.extract_text() or ''])
                except Exception:
                    pages.append([number, None])
                if number == 1:
                    try:
                        names = biggest(page)
                    except Exception:
                        names = []
                page.flush_cache()
    except Exception:
        pages = []
    if not pages:
        pages = [[number, text] for number, text in enumerate(quick, 1)]
    if not pages or any(text is None for _, text in pages):
        from pypdf import PdfReader
        reader = PdfReader(path)
        if not pages:
            pages = [[number, None] for number in range(1, min(len(reader.pages), MAX_PAGES) + 1)]
        for entry in pages:
            if entry[1] is None:
                try:
                    entry[1] = reader.pages[entry[0] - 1].extract_text() or ''
                except Exception:
                    entry[1] = ''
    result = [{'page': number, 'text': tidy(text)} for number, text in pages]
    scans = [entry for entry in result if len(re.findall(r'[^\W\d_]', entry['text'])) < SCANNED]
    if scans and ocr.ready():
        import pypdfium2 as pdfium
        document = pdfium.PdfDocument(path)
        try:
            for number, entry in enumerate(scans):
                if not ocr.left():
                    ocr.skipped += len(scans) - number
                    break
                text, lines = ocr.read(render(document, entry['page'] - 1))
                if text:
                    entry.update(text=text, ocr=True)
                    if entry['page'] == 1 and not names:
                        names = named(lines)
        finally:
            document.close()
    return result, names


# --- Word ---------------------------------------------------------------------------

# Word writes a text box or a shape's text twice, in mc:AlternateContent: as
# a DrawingML shape (mc:Choice) and again as VML for older readers
# (mc:Fallback). The fallback is not read. python-docx's qn() knows no 'mc'
# prefix, so the tag is spelled out.
FALLBACK = '{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback'


def read_docx(path):
    """The text of a Word file in document order: the headers, paragraphs, tables, text boxes and content controls, the footers.

    The first section's headers come first (its first-page header when it has
    a different first page, where templates often put the name and contacts),
    and its footers last; a line a header or footer repeats is read once.
    """
    import zipfile
    with zipfile.ZipFile(path) as archive:
        parts = [name.lower() for name in archive.namelist()]
    if 'word/document.xml' not in parts or any('vbaproject' in name or name.endswith('.bin') for name in parts):
        raise ValueError('not a plain Word document')
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    document = Document(path)
    blocks, sizes = [], []
    # Text with no size of its own is in the document's default size, 11 points when it names none.
    default = 11.0
    try:
        normal = document.styles['Normal'].font.size
        found = document.styles.element.find(f"{qn('w:docDefaults')}/{qn('w:rPrDefault')}/{qn('w:rPr')}/{qn('w:sz')}")
        if normal:
            default = normal.pt
        elif found is not None:
            default = int(found.get(qn('w:val'))) / 2
    except (KeyError, ValueError, TypeError):
        pass

    content = qn('w:txbxContent')

    def boxes(element, parent):
        # The text boxes in this paragraph, each once: not its VML fallback,
        # and not a box inside another, which is read with the one it is in.
        for box in element.iter(content):
            ancestor = box.getparent()
            while ancestor is not None and ancestor is not element and ancestor.tag not in (FALLBACK, content):
                ancestor = ancestor.getparent()
            if ancestor is None or ancestor is element:
                walk(box, parent)

    def paragraph(element, parent):
        item = Paragraph(element, parent)
        text = item.text.strip()
        if text:
            blocks.append(text)
            style = item.style
            size = max((run.font.size.pt for run in item.runs if run.font.size), default=0)
            if not size:
                size = style.font.size.pt if style is not None and style.font.size else default
            sizes.append((size, len(sizes), text, style is not None and style.name == 'Title'))
        boxes(element, parent)

    def table(element, parent):
        for row in Table(element, parent).rows:
            # A merged cell is the same cell under each column it spans: read once.
            cells, seen = [], []
            for cell in row.cells:
                if any(cell._tc is known for known in seen):
                    continue
                seen.append(cell._tc)
                before = len(blocks)
                walk(cell._tc, cell)
                cells.append(blocks[before:])
                del blocks[before:]
            if all(len(cell) <= 1 for cell in cells):
                line = ' | '.join(cell[0] for cell in cells if cell)
                if line:
                    blocks.append(line)
            else:
                for cell in cells:
                    if cell:
                        blocks.append('\n'.join(cell))

    def walk(element, parent):
        for child in element.iterchildren():
            if child.tag == qn('w:p'):
                paragraph(child, parent)
            elif child.tag == qn('w:tbl'):
                table(child, parent)
            elif child.tag in (qn('w:sdt'), qn('w:sdtContent'), qn('w:customXml')):
                walk(child, parent)
            if len(blocks) > 4000:
                return

    def story(part):
        """A header or footer, without the lines read already."""
        if part.is_linked_to_previous:
            return
        before = len(blocks)
        walk(part._element, part)
        seen, kept = set(blocks[:before]), []
        for block in blocks[before:]:
            if block not in seen:
                seen.add(block)
                kept.append(block)
        blocks[before:] = kept

    # Finding a document's sections reads its whole body: once.
    section = next(iter(document.sections[:1]), None)
    first = bool(section is not None and section.different_first_page_header_footer)
    if section is not None:
        for part in ([section.first_page_header] if first else []) + [section.header]:
            story(part)
    walk(document.element.body, document)
    if section is not None:
        for part in ([section.first_page_footer] if first else []) + [section.footer]:
            story(part)
    pages, page = [], ''
    for block in blocks:
        if page and len(page) + len(block) + 2 > PAGE_CHARS:
            pages.append(page)
            page = ''
        page = f'{page}\n\n{block}' if page else block[:PAGE_CHARS]
        if len(pages) >= MAX_PAGES:
            break
    if page and len(pages) < MAX_PAGES:
        pages.append(page)
    result = [{'page': number, 'text': tidy(text)} for number, text in enumerate(pages, 1)]
    # A name is the Title paragraph, or one in type larger than the rest near the top.
    known = sorted(size for size, *_ in sizes if size)
    usual = known[len(known) // 2] if known else 0
    return result, named([(1000.0 if title else size, order, text) for size, order, text, title in sizes[:15]
                          if (title or usual and size >= usual * 1.3) and len(text) <= NAME_CHARS])


# --- Images and OCR -----------------------------------------------------------------

def _png(picture):
    raw = io.BytesIO()
    picture.save(raw, 'PNG')
    picture.close()
    return raw.getvalue()


def read_image(path, ocr):
    """A photo, a scan or a screenshot of a CV, read by OCR: one page."""
    from PIL import Image, ImageOps
    with Image.open(path, formats=['PNG', 'JPEG']) as raw:
        if raw.width * raw.height > 50_000_000:
            raise ValueError('too many pixels')
        picture = ImageOps.exif_transpose(raw).convert('L')
    width, height = picture.size
    scale = min(math.sqrt(OCR_PIXELS / max(1, width * height)), max(1.0, min(3.0, OCR_SIDE / max(width, height))))
    if abs(scale - 1) > 0.05:
        resized = picture.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.LANCZOS)
        picture.close()
        picture = resized
    if not ocr.ready() or not ocr.left():
        ocr.skipped += 1
        picture.close()
        return [{'page': 1, 'text': ''}], []
    text, lines = ocr.read(_png(picture))
    return [{'page': 1, 'text': text, 'ocr': True}], named(lines)


class Ocr:
    """Tesseract in English, Russian and Uzbek, one page at a time, within a page count and a deadline."""

    def __init__(self, executable, tessdata, pages, seconds):
        self.executable, self.tessdata, self.pages = executable, tessdata, pages
        self.deadline = time.monotonic() + seconds
        self.read_pages = 0
        self.skipped = 0

    def ready(self):
        return bool(self.executable and self.tessdata)

    def left(self):
        """Whether another page may be read: fewer read than allowed, and time for it."""
        return self.read_pages < self.pages and self.deadline - time.monotonic() >= 5

    def read(self, png):
        """(text, lines as (height, top, text)) of one page image; ('', []) when tesseract fails."""
        self.read_pages += 1
        seconds = max(1.0, min(OCR_SECONDS, self.deadline - time.monotonic() - 2))
        try:
            done = subprocess.run(
                [self.executable, 'stdin', 'stdout', '--tessdata-dir', self.tessdata, '-l', LANGUAGES, '--oem', '1',
                 '--psm', '3', '-c', 'tessedit_create_tsv=1', '-c', 'tessedit_create_txt=0'],
                input=png, capture_output=True, timeout=seconds, check=False,
                env={'PATH': '/usr/bin:/bin', 'OMP_THREAD_LIMIT': '1', 'OMP_NUM_THREADS': '1'})
        except (subprocess.TimeoutExpired, OSError):
            return '', []
        if done.returncode or len(done.stdout) > 4_000_000:
            return '', []
        return tsv(done.stdout.decode('utf-8', 'replace'))


def tsv(table):
    """Tesseract's TSV as (text, lines): a line a row, a blank line between its blocks and paragraphs."""
    rows = [row.split('\t') for row in table.splitlines()[1:]]
    lines, order = {}, []
    for row in rows:
        if len(row) < 12 or row[0] != '5' or not row[11].strip():
            continue
        try:
            confidence = float(row[10])
            top, height = int(row[7]), int(row[9])
        except ValueError:
            continue
        if confidence < 20:
            continue
        key = (int(row[2]), int(row[3]), int(row[4]))
        if key not in lines:
            lines[key] = []
            order.append(key)
        lines[key].append((top, height, row[11].strip()))
    text, previous, measured = [], None, []
    for key in order:
        words = lines[key]
        line = ' '.join(word for _, _, word in words)
        if previous is not None and key[:2] != previous[:2]:
            text.append('')
        text.append(line)
        previous = key
        heights = sorted(height for _, height, _ in words)
        measured.append((heights[len(heights) // 2], min(top for top, _, _ in words), line))
    # As on a PDF page, only type that stands out from the rest can be a name.
    usual = sorted(height for height, _, _ in measured)[len(measured) // 2] if measured else 0
    found = [line for line in measured if line[0] >= usual * 1.25 and len(line[2]) <= NAME_CHARS]
    return tidy('\n'.join(text)), found


def main(argv):
    kind, path, executable, tessdata, pages, seconds = argv[1:7]
    seconds = max(5, min(120, int(float(seconds))))
    limits(seconds + 10)
    ocr = Ocr(executable, tessdata, max(0, int(pages)), seconds)
    if kind == 'pdf':
        result, names = read_pdf(path, ocr)
    elif kind == 'docx':
        result, names = read_docx(path)
    elif kind == 'image':
        result, names = read_image(path, ocr)
    else:
        raise ValueError('kind')
    sys.stdout.write(json.dumps({'pages': result, 'names': names, 'ocr_pages': ocr.read_pages,
                                 'ocr_skipped': ocr.skipped}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
