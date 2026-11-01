#!/usr/bin/env python3
"""How PdfCraft's small text edits come out, per PDF generator.

    PDFCRAFT_BENCH_DIR=folder PDFMASTER_PDFCRAFT_BIN=pdfcraft-cli python scripts/bench_pdfcraft.py

A local tool: the PDFs stay outside the repository and nothing here runs in the
image or CI. On the first page of every PDF it changes one word and one number
in up to four paragraphs, the way the editor will (editor_text with its row
breaks), and judges each result by what it renders and reads, never by
PdfCraft's own ok:

    text     pdfium and pypdf both read the new text, and in the edited box
             pdfium reads every row of it with the old row gone
    others   every other paragraph still reads as it did
    fit      the new text stays on the page and off its neighbours
    outside  no pixel changed outside the edited box
    stretch  letters stay within 8 % of their old width
    font     rows left alone keep their font, and the new letters are in the
             document's font or a close stand-in (Helvetica for Arial, Times
             for Times New Roman)

An edit then counts as one of:

    clean     every check passes
    fallback  it fails only on text or font, and passes once the new letters
              use a Noto face imported for them, as the editor's text check will
    refused   PdfCraft refused it or a check still fails: Cover and retype

The "loose" column repeats the 2026-10-31 bench's rule for comparison: clean,
plus edits whose only fault is one or two letters of a word of seven or more in
another font. Text, stretch and font look inside the edited box, so text
repeated elsewhere on the page is not mistaken for this paragraph's.

The output is counts: no file name, no document text. Each PDF is read in its
own process because pdfium is not thread-safe and a crash loses only that file.
"""
import argparse
from collections import Counter, defaultdict, namedtuple
from concurrent.futures import ThreadPoolExecutor
import ctypes
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

import numpy
from pypdf import PdfReader
import pypdfium2 as pdfium
import pypdfium2.raw as raw

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / 'processors' / 'assets' / 'fonts'
CLI_SECONDS = 120
FILE_SECONDS = 900
SCALE = 100 / 72  # 100 dpi
STRETCH = 0.08
OUTSIDE_PIXELS = 60
GENERATORS = (  # the first match over "Producer Creator" wins; anything else is "other"
    ('google-docs', r'google docs|google slides'), ('word', r'microsoft.{0,12}word|\bword for\b'),
    ('powerpoint', r'powerpoint'), ('excel', r'\bexcel\b'), ('microsoft-print', r'microsoft.{0,3}print to pdf'),
    ('libreoffice', r'libreoffice|openoffice'), ('wps', r'\bwps\b|kingsoft'), ('chrome', r'skia/pdf|chrom(e|ium)'),
    ('reportlab', r'reportlab'), ('quartz', r'quartz'), ('tex', r'\b(pdf|xe|lua)?tex\b|dvips'),
    ('ocr', r'tesseract|ocrmypdf|abbyy|finereader'), ('adobe', r'adobe|acrobat|distiller|indesign|illustrator'),
    ('ghostscript', r'ghostscript'), ('itext', r'itext'), ('pypdf', r'pypdf'), ('wkhtmltopdf', r'wkhtmltopdf|qt '))
WORDS = {'ru': 'Самарканд', 'uzc': 'Самарқанд', 'uzl': 'Samarqand', 'en': 'Samarkand'}
ISOLATION = ('HOME', 'TMPDIR', 'XDG_CACHE_HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_STATE_HOME', 'XDG_RUNTIME_DIR')
FAULTS = ('pdfcraft', 'text', 'others', 'fit', 'outside', 'stretch', 'font')
Letter = namedtuple('Letter', 'char x y width font')  # the centre of its box, top-left origin


def generator_of(producer, creator):
    """A fixed class name for the printed table: metadata can hold anything, even a person's name."""
    label = f'{producer or ""} {creator or ""}'.strip().lower()
    if not label:
        return 'unknown'
    return next((name for name, pattern in GENERATORS if re.search(pattern, label)), 'other')


def language_of(text):
    if re.search('[ўқғҳЎҚҒҲ]', text):
        return 'uzc'
    if re.search('[А-Яа-яЁё]', text):
        return 'ru'
    if re.search(r"[oOgG][‘ʻ'’]|\b(va|uchun|bilan|darsi)\b", text):
        return 'uzl'
    return 'en'


def kept(letter):
    return not letter.isspace() and letter not in '-\xad\ufffe\x02'


def norm(text):
    return ''.join(filter(kept, text or ''))


def family(font):
    """ArialMT, Arial-BoldMT and ABCDEF+Arial are one family; a nameless font (Type3) is ''."""
    name = re.sub(r'[-,].*', '', font.split('+')[-1])
    return re.sub(r'(PS)?MT$|PS$', '', name).lower()


def overlap(first, second):
    return max(0, min(first[2], second[2]) - max(first[0], second[0])), max(0, min(first[3], second[3]) - max(first[1], second[1]))


def close(name, sources):
    """The document's own font, or the near twin a viewer would not notice."""
    return (name in sources or (name == 'helvetica' and 'arial' in sources)
            or (name.startswith('times') and any(known.startswith('times') for known in sources)))


def new_letters_fault(fonts, sources, allowed=()):
    """Nothing when the new letters are close to the source; else 'font', or 'letters' for the loose rule's one or two."""
    off = sum(count for name, count in fonts.items() if not close(name, sources) and name not in allowed)
    if not off:
        return None
    return 'letters' if off <= 2 and sum(fonts.values()) > 6 else 'font'


def picks(paragraphs):
    """The paragraphs to edit: the longest and shortest body, a middling short one, a number on its own."""
    words = [item for item in paragraphs if re.search(r'[^\W\d_]{3}', item['text'])]
    body = sorted((item for item in words if len(item['text']) >= 60), key=lambda item: -len(item['text']))
    chosen = [('body', body[0])] if body else []
    if len(body) > 1:
        chosen.append(('body2', body[-1]))
    short = [item for item in words if len(item['text']) < 60]
    if short:
        chosen.append(('short', short[len(short) // 2]))
    numbers = [item for item in paragraphs if re.fullmatch(r'[\d ]+', item['text'].strip())]
    if numbers:
        chosen.append(('cell', numbers[-1]))
    return chosen


def cases(kind, paragraph, word):
    """(scenario, new editor_text, the new letters, their offset) for one paragraph."""
    text = paragraph.get('editor_text') or paragraph['text']
    if kind == 'cell':
        changed = re.sub(r'\d', '7', text)
        return [('number', changed, changed, 0)]
    found = []
    rows = text.split('\n')
    pattern = r"[^\W\d_][^\W\d_‘ʻ’']{3,}"
    words = re.findall(pattern, rows[-1] if len(rows) > 1 else text) or re.findall(pattern, text)
    if words:
        old = max(words, key=len)
        at = text.rfind(old)
        found.append(('word', text[:at] + word + text[at + len(old):], word, at))
    number = re.search(r'\d{2,}', text)
    if number:
        changed = '7' * len(number.group())
        found.append(('number', text[:number.start()] + changed + text[number.end():], changed, number.start()))
    return found


class Reading:
    """What page one of a PDF renders and reads."""

    def __init__(self, path):
        with pdfium.PdfDocument(str(path)) as document:
            page = document[0]
            self.width, self.height = page.get_size()
            self.pixels = page.render(scale=SCALE).to_numpy()[..., :3].astype(int)
            text = page.get_textpage()
            self.pdfium = norm(text.get_text_bounded())
            self.letters = []
            for index in range(raw.FPDFText_CountChars(text)):
                code = raw.FPDFText_GetUnicode(text, index)
                if not code or not kept(chr(code)):
                    continue
                left, right, bottom, top = (ctypes.c_double() for _ in range(4))
                raw.FPDFText_GetCharBox(text, index, left, right, bottom, top)
                name, flags = ctypes.create_string_buffer(256), ctypes.c_int()
                raw.FPDFText_GetFontInfo(text, index, name, 256, ctypes.byref(flags))
                self.letters.append(Letter(chr(code), (left.value + right.value) / 2, self.height - (bottom.value + top.value) / 2,
                                           right.value - left.value, family(name.value.decode('utf8', 'ignore'))))
            text.close()
            page.close()
        try:
            self.pypdf = norm(PdfReader(path).pages[0].extract_text())
        except Exception:
            self.pypdf = ''

    def inside(self, *rects):
        """The letters whose centres lie in one of the rects (top-left origin), in reading order."""
        return [letter for letter in self.letters if any(rect[0] - 2 <= letter.x <= rect[2] + 2 and rect[1] - 2 <= letter.y <= rect[3] + 2 for rect in rects)]


def reading(path):
    """Its Reading, or nothing when pdfium cannot open it."""
    try:
        return Reading(path)
    except pdfium.PdfiumError:
        return None


def locate(letters, wanted):
    """The run of letters spelling the wanted text, or nothing."""
    wanted = norm(wanted)
    at = ''.join(letter.char for letter in letters).find(wanted) if wanted else -1
    return letters[at:at + len(wanted)] if at >= 0 else []


def median_ratio(pairs):
    ratios = [new.width / old.width for old, new in pairs if old.width > 0.2]
    return statistics.median(ratios) if ratios else 1.0


def stretch_of(old_rows, new_rows, was, now):
    """The largest change of letter width, row by row: letter for letter where a row is untouched, and
    between the same letters in the same font where it changed. Ink widths, so a row at another size never compares."""
    worst = 1.0
    for old_row, new_row in zip(old_rows, new_rows):
        if old_row == new_row:
            start = old_row[:24]
            old, new = locate(was, start), locate(now, start)
            ratio = median_ratio(zip(old, new)) if len(norm(start)) >= 6 and old and len(old) == len(new) else 1.0
        else:
            known = {}
            for letter in locate(was, old_row):
                known.setdefault((letter.char, letter.font), letter)
            ratio = median_ratio((known[key], letter) for letter in locate(now, new_row) if (key := (letter.char, letter.font)) in known)
        worst = max(worst, ratio, key=lambda value: abs(value - 1))
    return worst


def box_reads_new(old_rows, new_rows, new_letters, was, now):
    """Whether the edited box itself now says the new text, so another place on the page saying it never counts.
    Only rows pdfium read in the box before the edit are held to this: pdfium and PdfCraft can read a glyph differently,
    and on some pages the box does not line up with pdfium's letters at all. A new row can spell the old one (mark in
    Samarkand), and that copy is not the old row left behind; a box that did not change still fails, whatever it spells."""
    before, after = ''.join(letter.char for letter in was), ''.join(letter.char for letter in now)
    rows = [(norm(old), norm(new)) for old, new in zip(old_rows, new_rows)]
    rows = [(old, new) for old, new in rows if old and old in before]
    return not rows or (norm(new_letters) in after and all(
        new in after and (old == new or (after != before and after.count(old) < before.count(old) + new.count(old))) for old, new in rows))


def judge(before, after, paragraph, paragraphs, draft, new_text, new_letters, allowed=()):
    """The checks one edited page fails; 'letters' is a font fault the loose rule forgives."""
    faults = set()
    expected = norm(new_letters)
    if expected not in after.pdfium or expected not in after.pypdf:
        faults.add('text')
    others = [item for item in paragraphs if item['paragraph'] != paragraph['paragraph'] and len(norm(item['text'])) >= 4]
    for reader in ('pdfium', 'pypdf'):
        was, now = getattr(before, reader), getattr(after, reader)
        if any(norm(item['text']) in was and norm(item['text']) not in now for item in others):
            faults.add('others')
    if draft[2] > after.width + 1 or draft[3] > after.height + 1 or any(width > 3 and height > 2 for width, height in (overlap(draft, item['rect']) for item in others)):
        faults.add('fit')
    if before.pixels.shape != after.pixels.shape:
        faults.add('outside')
    else:
        changed = numpy.abs(before.pixels - after.pixels).max(axis=2) > 40
        for rect in (paragraph['rect'], draft):
            changed[max(0, int((rect[1] - 4) * SCALE)):max(0, int((rect[3] + 4) * SCALE)), max(0, int((rect[0] - 6) * SCALE)):max(0, int((rect[2] + 6) * SCALE))] = False
        if int(changed.sum()) > OUTSIDE_PIXELS:
            faults.add('outside')
    was, now = before.inside(paragraph['rect']), after.inside(paragraph['rect'], draft)
    old_rows, new_rows = (paragraph.get('editor_text') or paragraph['text']).split('\n'), new_text.split('\n')
    if not box_reads_new(old_rows, new_rows, new_letters, was, now):
        faults.add('text')
    if abs(stretch_of(old_rows, new_rows, was, now) - 1) > STRETCH:
        faults.add('stretch')
    sources = {letter.font for letter in was} | {family(paragraph.get('font') or '')}
    written = locate(now, new_letters)
    kept_letters = [letter for letter in now if not any(letter is item for item in written)]
    if any(not close(letter.font, sources) for letter in kept_letters):
        faults.add('font')
    fault = new_letters_fault(Counter(letter.font for letter in written), sources, allowed)
    if fault:
        faults.add(fault)
    return faults


def run_cli(binary, root, steps):
    """One script under the same isolation as the editor: env and files at the root."""
    script = root / 'steps.json'
    script.write_text(json.dumps(steps, ensure_ascii=False))
    env = {'PATH': os.environ.get('PATH', ''), **dict.fromkeys(ISOLATION, str(root))}
    try:
        done = subprocess.run([binary, 'run', '--script', str(script), '--report', '--root', str(root)],
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, cwd=root, env=env, timeout=CLI_SECONDS)
        report = json.loads(done.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return {'ok': False, 'steps': []}
    return report if isinstance(report, dict) else {'ok': False, 'steps': []}


def result_of(report, index):
    value = report['steps'][index].get('result')
    return value[0] if isinstance(value, list) and value else value


def noto_for(font):
    style = 'Bold' if 'bold' in font.lower() else 'Regular'
    name = 'Serif' if re.search('times|serif|mincho|georgia|cambria', font, re.I) else 'Sans'
    return FONTS / f'Noto{name}-{style}.ttf'


def edit(binary, root, source, paragraph, new_text, face=None, at=0, new_letters=''):
    """Run one edit to a new file; returns (saved path, draft rect), or (None, None) when PdfCraft refuses it."""
    steps = [{'tool': 'doc_open', 'args': {'path': str(source)}}, {'tool': 'text_paragraphs', 'args': {'doc': 1, 'page': 1}}]
    args = {'doc': 1, 'page': 1, 'paragraph': paragraph['paragraph'], 'text': new_text}
    if face:
        font = root / face.name
        shutil.copyfile(face, font)
        steps.append({'tool': 'text_font_import', 'args': {'doc': 1, 'page': 1, 'path': str(font)}})
        probe = run_cli(binary, root, steps)
        if not probe.get('ok'):
            return None, None
        imported = result_of(probe, 2)
        resource = imported.get('resource') or imported.get('font_resource')
        if not resource:
            return None, None
        start = len(new_text[:at].encode())
        args['ranges'] = [{'range': [start, start + len(new_letters.encode())], 'font_resource': resource}]
    saved = root / ('noto.pdf' if face else 'plain.pdf')
    saved.unlink(missing_ok=True)
    steps += [{'tool': 'text_edit_layout', 'args': args}, {'tool': 'text_edit', 'args': args}, {'tool': 'doc_save', 'args': {'doc': 1, 'path': str(saved)}}]
    report = run_cli(binary, root, steps)
    if not report.get('ok') or not saved.is_file() or any(step.get('status') != 'ok' for step in report.get('steps', [])):
        return None, None
    layout = result_of(report, len(steps) - 3) or {}
    return saved, layout.get('draft_rect') or paragraph['rect']


def bench_file(path, binary):
    """Every edit of one PDF as {generator, alphabet, edits: [{outcome, faults, seconds}]}: fixed words and numbers only."""
    try:
        metadata = PdfReader(path).metadata or {}
        generator = generator_of(metadata.get('/Producer'), metadata.get('/Creator'))
    except Exception:
        generator = 'unknown'
    found = {'generator': generator, 'alphabet': 'latin', 'edits': [], 'no_text': False, 'unreadable': False}
    with tempfile.TemporaryDirectory(prefix='pdfcraft-bench-') as folder:
        root = Path(folder).resolve()
        source = root / 'source.pdf'
        shutil.copyfile(path, source)
        report = run_cli(binary, root, [{'tool': 'doc_open', 'args': {'path': str(source)}}, {'tool': 'text_paragraphs', 'args': {'doc': 1, 'page': 1}}])
        if not report.get('ok'):
            found['edits'].append({'outcome': 'refused', 'faults': ['pdfcraft'], 'seconds': 0})
            return found
        paragraphs = result_of(report, 1)['paragraphs']
        language = language_of(' '.join(item['text'] for item in paragraphs))
        found['alphabet'] = 'cyrillic' if language in ('ru', 'uzc') else 'latin'
        before = reading(source)
        if before is None:
            found['unreadable'] = True
            return found

        def verdict(saved, draft, allowed=()):
            after = reading(saved)
            return {'text'} if after is None else judge(before, after, paragraph, paragraphs, draft, new_text, new_letters, allowed)
        for kind, paragraph in picks(paragraphs):
            for scenario, new_text, new_letters, at in cases(kind, paragraph, WORDS[language]):
                started = time.monotonic()
                saved, draft = edit(binary, root, source, paragraph, new_text)
                seconds = time.monotonic() - started
                if not saved:
                    found['edits'].append({'outcome': 'refused', 'faults': ['pdfcraft'], 'seconds': seconds})
                    continue
                faults = verdict(saved, draft)
                row = {'outcome': 'clean' if not faults else 'refused', 'faults': sorted(faults), 'seconds': seconds, 'loose': faults <= {'letters'}}
                if faults & {'text', 'font', 'letters'}:
                    face = noto_for(paragraph.get('font') or '')
                    saved, draft = edit(binary, root, source, paragraph, new_text, face, at, new_letters)
                    if saved and not verdict(saved, draft, {family(face.stem)}):
                        row['outcome'] = 'fallback'
                found['edits'].append(row)
        found['no_text'] = not found['edits']
    return found


def one_file(path, binary):
    """A crash, a timeout or an unreadable file costs that file alone, and says nothing about it."""
    try:
        done = subprocess.run([sys.executable, '-I', __file__, '--one', str(path)], capture_output=True, text=True,
                              timeout=FILE_SECONDS, env={**os.environ, 'PDFMASTER_PDFCRAFT_BIN': binary})
        return json.loads(done.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def percent(part, whole):
    return f'{100 * part / whole:.0f}' if whole else '-'


def table(title, groups):
    print(f'\n{title:<22}{"files":>6}{"edits":>6}{"clean":>6}{"fallback":>9}{"refused":>8}{"loose":>6}{"clean%":>7}{"+fallback%":>11}{"loose%":>7}{"ms":>6}')
    for name, files in sorted(groups.items()):
        edits = [row for found in files for row in found['edits']]
        count = Counter(row['outcome'] for row in edits)
        loose = sum(1 for row in edits if row.get('loose'))
        pace = statistics.median(row['seconds'] for row in edits) * 1000 if edits else 0
        print(f'{name:<22}{len(files):>6}{len(edits):>6}{count["clean"]:>6}{count["fallback"]:>9}{count["refused"]:>8}{loose:>6}'
              f'{percent(count["clean"], len(edits)):>7}{percent(count["clean"] + count["fallback"], len(edits)):>11}{percent(loose, len(edits)):>7}{pace:>6.0f}')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--jobs', type=int, default=min(6, os.cpu_count() or 1), help='PDFs read at once')
    parser.add_argument('--one', help=argparse.SUPPRESS)
    args = parser.parse_args()
    binary = os.environ.get('PDFMASTER_PDFCRAFT_BIN')
    if not binary or not Path(binary).is_file():
        parser.error('set PDFMASTER_PDFCRAFT_BIN to the pdfcraft-cli binary')
    binary = str(Path(binary).resolve())  # run_cli starts it from inside a temp folder
    if args.one:
        json.dump(bench_file(args.one, binary), sys.stdout)
        return 0
    folder = os.environ.get('PDFCRAFT_BENCH_DIR')
    if not folder or not Path(folder).is_dir():
        parser.error('set PDFCRAFT_BENCH_DIR to a folder of PDFs')
    # run_cli takes a binary that cannot start for PdfCraft refusing: a table of refusals that exits 0.
    try:
        subprocess.run([binary, '--version'], stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=CLI_SECONDS)
    except (OSError, subprocess.SubprocessError) as error:
        parser.error(f'PDFMASTER_PDFCRAFT_BIN cannot start: {error}')
    paths = sorted(path for path in Path(folder).rglob('*') if path.is_file() and path.suffix.lower() == '.pdf')
    with ThreadPoolExecutor(max(1, args.jobs)) as pool:
        results = list(pool.map(lambda path: one_file(path, binary), paths))
    done = [found for found in results if found]
    edited = [found for found in done if found['edits']]
    by_generator, by_alphabet = defaultdict(list), defaultdict(list)
    for found in edited:
        by_generator[found['generator']].append(found)
        by_alphabet[f'{found["generator"]} {found["alphabet"]}'].append(found)
    print(f'{len(paths)} PDFs, {len(paths) - len(done)} lost to a crash or timeout, {sum(found["unreadable"] for found in done)} that pdfium cannot open, {sum(found["no_text"] for found in done)} with nothing to edit on page one.')
    table('generator', {**by_generator, '(all)': edited})
    table('generator, alphabet', by_alphabet)
    faults = Counter(fault for found in edited for row in found['edits'] if row['outcome'] == 'refused' for fault in row['faults'])
    tried = Counter(fault for found in edited for row in found['edits'] if row['outcome'] != 'clean' for fault in row['faults'])
    print('\nchecks failed by refused edits: ' + ', '.join(f'{name} {faults[name]}' for name in FAULTS))
    print('checks failed at first try, fallback included: ' + ', '.join(f'{name} {tried[name]}' for name in (*FAULTS, 'letters')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
