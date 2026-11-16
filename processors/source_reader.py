"""The bounded child that reads one Word or text file a category is made from. Run by extraction.read_source, never imported for use.

A customer who picks a category may attach a `.docx`, an old binary `.doc`
or a `.txt` beside a PDF (upload purpose 'ai_source'). This program reads one
such file and prints its text as JSON, already cut into the parts the model
is shown (source_text.pages): {"parts": [text, ...], "truncated": false}.
Part N is "page" N + 1 of a citation, and for a `.doc` or `.txt` the number of
parts is the page count the upload stored, because both cut the same text with
the same function.

It runs as its own process with its own limits (CPU, file size, open files,
address space; extraction.py adds a wall-clock timeout and kills its whole
process group), because the file is the customer's. It imports nothing of the
app: only the standard library, python-docx's XML stack and source_text, which
is loaded from beside this file because `-I` leaves this folder off the path.
It writes nothing but antiword's output to an anonymous temporary file.

It reads what is there and reports when it stopped early ("truncated"), never
cutting silently: a file longer than any source may be is refused by the
caller, not quietly shortened.

Usage: source_reader.py KIND PATH ANTIWORD SECONDS
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def _source_text():
    spec = importlib.util.spec_from_file_location('source_text', Path(__file__).resolve().with_name('source_text.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


source_text = _source_text()

# The most text read from one file: as many parts as any upload may have.
# A source this long cannot fit a draft whatever its plan, so past it the
# reading stops and says so.
READ_CHARS = source_text.MAX_PARTS * source_text.PAGE_CHARS
# What this child may write: antiword's output (refused past MAX_TEXT_BYTES)
# and the report on stdout, which the caller also holds to its own cap.
FILE_BYTES = 16 * 1024 * 1024


def limits(seconds):
    """CPU, file size, open files and, on Linux, address space: inherited by antiword too."""
    import resource
    caps = [(resource.RLIMIT_CPU, (seconds, seconds + 5)), (resource.RLIMIT_FSIZE, (FILE_BYTES, FILE_BYTES)),
            (resource.RLIMIT_NOFILE, (128, 128)), (resource.RLIMIT_CORE, (0, 0))]
    if sys.platform.startswith('linux'):
        caps.append((resource.RLIMIT_AS, (2048 * 1024 * 1024,) * 2))
    for name, value in caps:
        try:
            resource.setrlimit(name, value)
        except (ValueError, OSError):
            pass
    # Short of memory, the kernel ends this reading before the process that
    # asked for it, which in the bot's container is the bot itself.
    if sys.platform.startswith('linux'):
        try:
            with open('/proc/self/oom_score_adj', 'w') as score:
                score.write('1000')
        except OSError:
            pass
    os.umask(0o077)


class Text:
    """Blocks of text in reading order, up to READ_CHARS; `truncated` once one did not fit."""

    def __init__(self):
        self.blocks, self.size, self.truncated = [], 0, False

    def add(self, block):
        if self.truncated:
            return
        if self.size + len(block) + 1 > READ_CHARS:
            self.truncated = True
            return
        self.blocks.append(block)
        self.size += len(block) + 1

    def text(self):
        return '\n'.join(self.blocks)


# --- Word -------------------------------------------------------------------------------

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
# Word writes a text box twice, as a DrawingML shape (mc:Choice) and again as
# VML for older readers (mc:Fallback): the fallback is not read.
FALLBACK = '{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback'
BOX = W + 'txbxContent'
# Text a reader of the document sees: what a run holds, a tab, a line break.
# Deleted text is w:delText and field codes w:instrText, so neither is read.
CHARACTERS = {W + 't': None, W + 'tab': '\t', W + 'br': '\n', W + 'cr': '\n', W + 'noBreakHyphen': '-'}
# Not read in a paragraph: a text box's VML copy, a text box itself (read after
# the paragraph), a tracked deletion, and text a tracked move took elsewhere.
SKIPPED = frozenset({FALLBACK, BOX, W + 'moveFrom', W + 'del'})
WRAPPERS = frozenset({W + 'sdt', W + 'sdtContent', W + 'customXml', W + 'smartTag'})


def _characters(element, out):
    """The visible characters of a paragraph in order, without its text boxes, which are read after it."""
    for child in element:
        tag = child.tag
        if not isinstance(tag, str) or tag in SKIPPED:
            continue
        if tag in CHARACTERS:
            out.append((child.text or '') if CHARACTERS[tag] is None else CHARACTERS[tag])
        else:
            _characters(child, out)


def _boxes(element):
    """The text boxes in a paragraph, each once: not its VML copy, and not one inside another box."""
    found = []

    def look(node):
        for child in node:
            if not isinstance(child.tag, str) or child.tag == FALLBACK:
                continue
            if child.tag == BOX:
                found.append(child)
            else:
                look(child)
    look(element)
    return found


def _rows(element):
    """A table's rows, or a row's cells: its direct children of that tag, and those inside content controls."""
    for child in element:
        if child.tag in (W + 'tr', W + 'tc'):
            yield child
        elif child.tag in WRAPPERS:
            yield from _rows(child)


def _walk(element, text):
    for child in element:
        if text.truncated:
            return
        _block(child, text)


def _block(element, text):
    """One paragraph (then its text boxes), table or content control."""
    tag = element.tag
    if tag == W + 'p':
        out = []
        _characters(element, out)
        line = ''.join(out).strip()
        if line:
            text.add(line)
        for box in _boxes(element):
            _walk(box, text)
    elif tag == W + 'tbl':
        _table(element, text)
    elif tag in WRAPPERS:
        _walk(element, text)


def _table(element, text):
    """One line a row, its cells joined by " | ", when every cell holds one block; else a block a cell.

    Each cell is read once as it stands in the file: a cell merged across
    columns is one w:tc, and the cells below a vertical merge are empty.
    """
    for row in _rows(element):
        if text.truncated:
            return
        cells = []
        for cell in _rows(row):
            if cell.tag != W + 'tc':
                continue
            inner = Text()
            _walk(cell, inner)
            cells.append(inner.blocks)
        if all(len(cell) <= 1 for cell in cells):
            line = ' | '.join(cell[0] for cell in cells if cell)
            if line:
                text.add(line)
        else:
            for cell in cells:
                if cell:
                    text.add('\n'.join(cell))


def read_docx(path):
    """A Word file's body in document order: paragraphs, tables, text boxes and content controls.

    Headers, footers, footnotes and comments are not read, and nothing is
    reordered or dropped as a page footer: the text is the document's own, so
    a quotation the model copies from it is found again. The body is parsed
    as a stream, one top-level paragraph or table at a time, so a long thesis
    never sits whole in memory as a tree.
    """
    import zipfile
    from lxml import etree
    text = Text()
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        lowered = [name.lower() for name in names]
        if 'word/document.xml' not in lowered or any('vbaproject' in name or name.endswith('.bin') for name in lowered):
            raise ValueError('not a plain Word document')
        with archive.open(names[lowered.index('word/document.xml')]) as stream:
            depth = 0
            for event, element in etree.iterparse(stream, events=('start', 'end'), resolve_entities=False, no_network=True,
                                                  load_dtd=False, huge_tree=False, remove_comments=True, remove_pis=True):
                if event == 'start':
                    depth += 1
                    continue
                depth -= 1
                # w:document is depth 1 and w:body 2: an element ending at 2 is one of the body's blocks.
                if depth != 2:
                    continue
                _block(element, text)
                # What has been read is let go of: the body keeps no block behind the one being parsed.
                element.clear()
                while element.getprevious() is not None:
                    del element.getparent()[0]
                if text.truncated:
                    break
    return text


# --- Plain text and old Word ------------------------------------------------------------

def read_text(path):
    """A `.txt` file decoded as the upload decoded it (source_text.decode)."""
    with open(path, 'rb') as stream:
        raw = stream.read(source_text.MAX_TEXT_BYTES + 1)
    text = Text()
    if len(raw) > source_text.MAX_TEXT_BYTES:
        text.truncated = True
        return text
    decoded = source_text.decode(raw)
    if decoded is None:
        raise ValueError('not text')
    text.blocks = [decoded]
    return text


def read_doc(path, executable, deadline):
    """An old Word file's text as antiword prints it, with its picture marks left out, as the upload counted it."""
    if not executable:
        raise ValueError('no antiword')
    text = Text()
    with tempfile.TemporaryDirectory(prefix='docmaster-antiword-') as home, tempfile.TemporaryFile() as output:
        completed = subprocess.run(source_text.doc_command(executable, Path(path).absolute()),
                                   stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL, cwd=home,
                                   timeout=max(1.0, deadline - time.monotonic()), check=False,
                                   env={**os.environ, 'HOME': home})
        if completed.returncode != 0:
            raise ValueError('antiword failed')
        if output.tell() > source_text.MAX_TEXT_BYTES:
            text.truncated = True
            return text
        output.seek(0)
        text.blocks = [source_text.doc_text(output.read())]
    return text


def main(argv):
    kind, path, executable, seconds = argv[1:5]
    seconds = max(5, min(120, int(float(seconds))))
    limits(seconds + 5)
    deadline = time.monotonic() + seconds
    if kind == 'docx':
        text = read_docx(path)
    elif kind == 'text':
        text = read_text(path)
    elif kind == 'doc':
        text = read_doc(path, executable, deadline)
    else:
        raise ValueError('kind')
    parts = [] if text.truncated else source_text.pages(text.text())
    if len(parts) > source_text.MAX_PARTS:
        parts, text.truncated = [], True
    sys.stdout.write(json.dumps({'parts': parts, 'truncated': text.truncated}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
