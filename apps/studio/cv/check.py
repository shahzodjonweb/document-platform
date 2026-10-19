"""Read a rendered CV back and list what a reader would notice.

The renderer is careful, but careful code still overlaps a date with a title
or runs a sidebar off the page now and then; this reads the finished PDF with
pdfplumber and reports, in plain words:

1. more than two pages;
2. a character outside the page;
3. a character outside every frame text may sit in (when the frames are given);
4. two words drawn over each other;
5. text that does not stand out from what it is printed on — the fill under a
   word is the smallest filled rectangle or shape containing its centre, white
   when there is none, and a word on a picture is always a problem;
6. a required string (the name, a contact, a skill group, a language) missing,
   and the name missing from page 1;
7. a character in a font that is not one of the bundled Noto faces;
8. a page 2 with almost nothing on it.

The job does not run this (the Cyrillic read-back in the pipeline does); tests
run it on every template, and `python -m apps.studio.cv.sample --check` runs it
by hand.
"""
import re

from . import fonts

MAX_PAGES = 2
WIDOW_CHARS = 300
APOSTROPHES = str.maketrans({mark: "'" for mark in '‘’ʻʼ`´'})


def _colour(value):
    """A pdfplumber colour as hex, or None when it cannot be read."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        value = (value,)
    value = tuple(value)
    if len(value) == 1:
        red = green = blue = value[0]
    elif len(value) == 3:
        red, green, blue = value
    elif len(value) == 4:
        cyan, magenta, yellow, key = value
        red, green, blue = ((1 - cyan) * (1 - key), (1 - magenta) * (1 - key), (1 - yellow) * (1 - key))
    else:
        return None
    try:
        return '%02X%02X%02X' % tuple(round(max(0.0, min(1.0, float(part))) * 255) for part in (red, green, blue))
    except (TypeError, ValueError):
        return None


def _normal(text):
    return ' '.join(str(text or '').translate(APOSTROPHES).casefold().split())


def _url(text):
    return re.sub(r'^(?:https?://)?(?:www\.)?', '', _normal(text)).rstrip('/')


def _digits(text):
    return re.sub(r'\D', '', str(text or ''))


def _inside(x, y, box, slack=0.5):
    x0, top, x1, bottom = box
    return x0 - slack <= x <= x1 + slack and top - slack <= y <= bottom + slack


def _frames(frames, number):
    if not frames:
        return None
    return frames.get(number, frames.get(str(number)))


def _page_text(page, boxes):
    """The page's text, frame by frame when the frames are known, so columns do not interleave."""
    if not boxes:
        return page.extract_text() or ''
    parts = []
    for x0, top, x1, bottom in boxes:
        box = (max(0, x0 - 1), max(0, top - 1), min(page.width, x1 + 1), min(page.height, bottom + 1))
        parts.append(page.within_bbox(box).extract_text() or '')
    return '\n'.join(parts)


def problems(path, frames=None, required=()):
    """Everything wrong with the CV at `path`, as sentences; [] when it reads well.

    `frames` is `metadata['frames']` from `render_cv`; `required` the strings
    the CV must show (phones are matched by their digits, links without their
    scheme). The name the PDF names as its author must be on page 1.
    """
    import pdfplumber
    from apps.studio.slides import contrast_ratio
    allowed = set(fonts.internal_names().values())
    found = []
    with pdfplumber.open(str(path)) as pdf:
        pages = pdf.pages
        if len(pages) > MAX_PAGES:
            found.append(f'{len(pages)} pages; a CV has at most {MAX_PAGES}')
        texts = []
        for number, page in enumerate(pages, 1):
            boxes = _frames(frames, number)
            chars = [char for char in page.chars if char['text'].strip()]
            outside = [char for char in chars if char['x0'] < -0.5 or char['x1'] > page.width + 0.5
                       or char['top'] < -0.5 or char['bottom'] > page.height + 0.5]
            if outside:
                found.append(f'page {number}: {len(outside)} characters outside the page, from '
                             f'"{"".join(char["text"] for char in outside[:12])}"')
            if boxes:
                loose = [char for char in chars if not any(
                    _inside((char['x0'] + char['x1']) / 2, (char['top'] + char['bottom']) / 2, box) for box in boxes)]
                if loose:
                    found.append(f'page {number}: {len(loose)} characters outside every frame, from '
                                 f'"{"".join(char["text"] for char in loose[:12])}"')
            faces = {str(char.get('fontname', '')).split('+', 1)[-1] for char in chars}
            strange = sorted(face for face in faces if face not in allowed)
            if strange:
                found.append(f'page {number}: text in fonts that are not bundled: {", ".join(strange)}')
            words = sorted(page.extract_words(extra_attrs=['size', 'non_stroking_color']),
                           key=lambda word: word['top'])
            for index, word in enumerate(words):
                for other in words[index + 1:]:
                    if other['top'] >= word['bottom']:
                        break
                    across = min(word['x1'], other['x1']) - max(word['x0'], other['x0'])
                    down = min(word['bottom'], other['bottom']) - max(word['top'], other['top'])
                    smaller = min(word['bottom'] - word['top'], other['bottom'] - other['top'])
                    if across > 1 and smaller > 0 and down > 0.4 * smaller:
                        found.append(f'page {number}: "{word["text"]}" and "{other["text"]}" overlap')
            fills = [shape for shape in [*page.rects, *page.curves] if shape.get('fill')]
            for word in words:
                x, y = (word['x0'] + word['x1']) / 2, (word['top'] + word['bottom']) / 2
                if any(_inside(x, y, (image['x0'], image['top'], image['x1'], image['bottom']), 0)
                       for image in page.images):
                    found.append(f'page {number}: "{word["text"]}" is printed on a picture')
                    continue
                under = [shape for shape in fills
                         if _inside(x, y, (shape['x0'], shape['top'], shape['x1'], shape['bottom']), 0)]
                under.sort(key=lambda shape: (shape['x1'] - shape['x0']) * (shape['bottom'] - shape['top']))
                ground = _colour(under[0].get('non_stroking_color')) if under else 'FFFFFF'
                ink = _colour(word.get('non_stroking_color'))
                if not ground or not ink:
                    continue
                target = 3.0 if word.get('size', 0) >= 18 else 4.5
                ratio = contrast_ratio(ink, ground)
                if ratio < target - 0.01:
                    found.append(f'page {number}: "{word["text"]}" is #{ink} on #{ground} ({ratio:.2f}:1)')
            text = _page_text(page, boxes)
            texts.append(text)
            if number == 2 and len(re.sub(r'\s', '', text)) < WIDOW_CHARS:
                found.append(f'page 2 holds only {len(re.sub(r"\s", "", text))} characters')
        author = str((pdf.metadata or {}).get('Author') or '').strip()
        if author and texts and _normal(author) not in _normal(texts[0]):
            found.append(f'the name "{author}" is not on page 1')
        whole = _normal('\n'.join(texts))
        # A link or an email may break across lines in a narrow column: match it without the breaks.
        digits, links = _digits(whole), re.sub(r'\s', '', whole)
        for wanted in required:
            wanted = str(wanted or '').strip()
            if not wanted:
                continue
            if re.fullmatch(r'[\d\s()+\-.]{7,}', wanted):
                present = _digits(wanted) in digits
            elif re.search(r'\w\.\w', wanted) and ' ' not in wanted:
                present = _url(wanted) in links
            else:
                present = _normal(wanted) in whole
            if not present:
                found.append(f'"{wanted}" is missing')
    return found
