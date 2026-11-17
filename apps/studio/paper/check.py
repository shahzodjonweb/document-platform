"""Read a drawn category paper back and list what a reader would notice (architecture 6.5).

The engine is careful, but careful code still runs a signature off the frame
or loses an addressee line now and then; this reads the finished PDF with
pdfplumber, as cv/check.py reads a CV, and reports in plain words:

1. a character outside the page, or outside the frame and every place the
   page furniture may print (the number, the running header);
2. two words drawn over each other;
3. text in a font that is not one of the bundled Noto faces;
4. a verified fact or a fixed label the paper draws missing from its text;
5. a page count the template's page rule does not allow;
6. Cyrillic in an Uzbek or English paper (Uzbek papers are Latin only);
7. a last page less than a tenth full;
8. what the engine said of the build: the emergency fallback, a block drawn
   plain, characters the face could not draw.

`problems(path, expect)` reads the PDF; `expect` is what the paper should be,
made by `expect_for` from the artifact render_paper returned and the content
it drew. The job does not run this: tests run it on every template's samples
(tests/paper_family.py) and `python -m apps.studio.paper.sample --check` runs
it by hand.
"""
import re

from ..categories.catalogue import LOCALES
from ..cv import fonts
from ..language import CYRILLIC

# The PDF plan cap; a paper is quoted at most this, and output_cap is the quote plus one.
PLAN_CAP = 35
# Below this share of its frame, a last page is a stub (architecture 6.5).
STUB_MIN = 0.10
# The engine's codes a sample must not carry: each means the paper is not drawn as its template draws it.
BROKEN = ('template_fallback', 'block_fallback:', 'glyphs_dropped')
LONGER = 'longer_than_quoted'
OVERLAPS_SHOWN = 5
# Fields whose value is a code or a list, never printed as typed: a choice is an id such as `self_study`, a flag
# shapes a block, a file is a name, a list is drawn as the part's items.
UNPRINTED = frozenset(('choice', 'flag', 'file', 'list'))
APOSTROPHES = str.maketrans({mark: "'" for mark in '‘’ʻʼ`´'})
# A run of underscores in a label is drawn as a rule to write on (text_rules), not as text: the pieces between
# the runs are what a reader sees.
RULE_RUN = re.compile(r'_{2,}')
# How far a list with `gutter` hangs its markers left of the frame, in ems of the body size: "40)" and the gap.
GUTTER_EMS = 3.0
SPACES = re.compile(r'[\s   ]+')


def normal(text):
    """Text as compared: apostrophes alike, case folded, every run of spaces (no-break ones too) one space."""
    return SPACES.sub(' ', str(text or '').translate(APOSTROPHES).casefold()).strip()


def _squeezed(text):
    return SPACES.sub('', normal(text))


def _inside(x, y, box, slack=0.5):
    x0, top, x1, bottom = box
    return x0 - slack <= x <= x1 + slack and top - slack <= y <= bottom + slack


def _boxes(expect, number):
    """Where text may sit on page `number`: the frame and the furniture's places, or None when not known.

    A paper with a gutter list may also print in a band as wide as the hang
    left of the frame: the list sets its markers in the margin on purpose.
    """
    frames = expect.get('frames') or {}
    if not frames:
        return None
    kind = 'first' if number == 1 else 'later'
    inside = [tuple(box) for box in (frames.get(kind) or ())]
    hang = float(expect.get('gutter') or 0)
    margin = [(x0 - hang, top, x0, bottom) for x0, top, x1, bottom in inside] if hang > 0 else []
    return inside + margin + [tuple(box) for box in ((expect.get('furniture') or {}).get(kind) or ())]


def _overlaps(chars):
    """Pairs of characters drawn over each other, as (char, other), at most one pair per place.

    Characters, not words: pdfplumber merges two strings drawn on top of each
    other into one garbled word, so a word-level test never sees them. A sweep
    from left to right keeps it to the characters whose spans meet.
    """
    found, active, seen = [], [], set()
    for char in sorted(chars, key=lambda char: char['x0']):
        active = [other for other in active if other['x1'] > char['x0']]
        for other in active:
            across = min(char['x1'], other['x1']) - max(char['x0'], other['x0'])
            down = min(char['bottom'], other['bottom']) - max(char['top'], other['top'])
            narrower = min(char['x1'] - char['x0'], other['x1'] - other['x0'])
            smaller = min(char['bottom'] - char['top'], other['bottom'] - other['top'])
            if narrower > 0 and smaller > 0 and across > 0.4 * narrower and down > 0.4 * smaller:
                place = (round(other['x0'] / 20), round(other['top'] / 10))
                if place not in seen:
                    seen.add(place)
                    found.append((other, char))
        active.append(char)
    return found


def _word_at(words, char):
    x, y = (char['x0'] + char['x1']) / 2, (char['top'] + char['bottom']) / 2
    return next((word['text'] for word in words if _inside(x, y, (word['x0'], word['top'], word['x1'], word['bottom']),
                                                           0)), char['text'])


def _pages_problem(count, expect):
    """The page count against the rule, or None. See `expect_for` for the keys."""
    rule = expect.get('rule')
    if not rule:
        return None
    quoted = max(1, int(expect.get('quoted') or 1))
    target = {'fixed': int(expect.get('rule_pages') or quoted), 'count': quoted}.get(rule, quoted + 1)
    if count > PLAN_CAP + 1:
        return f'{count} pages; no paper is drawn past {PLAN_CAP + 1}'
    if rule == 'fixed' and count > target + 1:
        return f'{count} pages; a fixed paper of {target} takes at most one page more, with its closing group'
    if count > target and not expect.get('longer'):
        return (f'{count} pages; the {rule} rule allows {target} for a quote of {quoted}, and the paper does not say '
                f'it came out longer')
    return None


def problems(path, expect=None):
    """Everything wrong with the paper at `path`, as sentences; [] when it reads well.

    `expect` (all keys optional, see `expect_for`): `frames` and `furniture`
    (the artifact's metadata), `gutter` (points a gutter list may hang left
    of the frame), `rule`, `rule_pages`, `quoted` and `longer` (the page
    rule), `facts` and `labels` (strings the text must hold, a label's
    underscore runs read as the rules they are drawn as), `locale`,
    `stub_min`, and `warnings` (the artifact's codes).
    """
    import pdfplumber
    expect = expect or {}
    allowed = set(fonts.internal_names().values())
    found = [f'the engine says {code}' for code in expect.get('warnings') or ()
             if any(code.startswith(broken) for broken in BROKEN)]
    texts, flows = [], []
    with pdfplumber.open(str(path)) as pdf:
        pages = pdf.pages
        wrong = _pages_problem(len(pages), expect)
        if wrong:
            found.append(wrong)
        for number, page in enumerate(pages, 1):
            chars = [char for char in page.chars if char['text'].strip()]
            outside = [char for char in chars if char['x0'] < -0.5 or char['x1'] > page.width + 0.5
                       or char['top'] < -0.5 or char['bottom'] > page.height + 0.5]
            if outside:
                found.append(f'page {number}: {len(outside)} characters outside the page, from '
                             f'"{"".join(char["text"] for char in outside[:12])}"')
            boxes = _boxes(expect, number)
            if boxes:
                loose = [char for char in chars if char not in outside and not any(
                    _inside((char['x0'] + char['x1']) / 2, (char['top'] + char['bottom']) / 2, box) for box in boxes)]
                if loose:
                    found.append(f'page {number}: {len(loose)} characters outside the frame, from '
                                 f'"{"".join(char["text"] for char in loose[:12])}"')
            faces = {str(char.get('fontname', '')).split('+', 1)[-1] for char in chars}
            strange = sorted(face for face in faces if face not in allowed)
            if strange:
                found.append(f'page {number}: text in fonts that are not bundled: {", ".join(strange)}')
            crossed = _overlaps(chars)
            if crossed:
                words = page.extract_words()
                for char, other in crossed[:OVERLAPS_SHOWN]:
                    found.append(f'page {number}: "{char["text"]}" and "{other["text"]}" overlap, in '
                                 f'"{_word_at(words, char)}"')
                if len(crossed) > OVERLAPS_SHOWN:
                    found.append(f'page {number}: {len(crossed) - OVERLAPS_SHOWN} more places where text overlaps')
            # Two readings: by position (lines across the page) and in drawing order, which keeps a table cell's
            # lines together where the positional reading interleaves two cells that both wrap.
            texts.append(page.extract_text() or '')
            flows.append(page.extract_text(use_text_flow=True) or '')
            if number == len(pages) > 1:
                share = _fill(chars, expect)
                stub = expect.get('stub_min', STUB_MIN)
                if share is not None and stub and share < stub:
                    found.append(f'the last page is {share:.0%} full, under {stub:.0%}')
    whole = normal('\n'.join(texts))
    if expect.get('locale') in ('uz', 'en'):
        cyrillic = CYRILLIC.findall(whole)
        if cyrillic:
            found.append(f'{len(cyrillic)} Cyrillic letters in an {expect["locale"]} paper, from '
                         f'"{"".join(cyrillic[:12])}"')
    readings = (whole, normal('\n'.join(flows)))
    squeezed = tuple(_squeezed(reading) for reading in readings)
    for kind in ('facts', 'labels'):
        for wanted in expect.get(kind) or ():
            if not _present(wanted, readings, squeezed):
                found.append(f'the {kind[:-1]} "{wanted}" is missing')
    return found


def _present(wanted, readings, squeezed):
    """Whether the text holds `wanted`: every piece of it between its underscore rules, in either reading."""
    pieces = [normal(piece) for piece in RULE_RUN.split(str(wanted or ''))]
    pieces = [piece for piece in pieces if piece.strip(' ,.;:')]
    for piece in pieces:
        # Squeezed: letters set with tracking come back as spaced words, a word in a narrow cell may break.
        tight = _squeezed(piece)
        if not any(piece in reading for reading in readings) and not any(tight in reading for reading in squeezed):
            return False
    return True


def _fill(chars, expect):
    """How far down its frame the last page's text reaches, as a share; None when the frame is not known."""
    frames = (expect.get('frames') or {}).get('later') or ()
    if not frames:
        return None
    x0, top, x1, bottom = frames[0]
    inside = [char for char in chars if _inside((char['x0'] + char['x1']) / 2, (char['top'] + char['bottom']) / 2,
                                                 (x0, top, x1, bottom))]
    if not inside:
        return 0.0
    return round(max(0.0, (max(char['bottom'] for char in inside) - top) / (bottom - top)), 3)


# ---------------------------------------------------------------- what a paper should be


def _filled(text, ctx):
    """A label's text with its {field} slots filled from the facts; None when a slot has no fact to fill it."""
    missing = False

    def fill(found):
        nonlocal missing
        value = ctx.fact(found.group(1))
        if value is None:
            missing = True
            return ''
        return value
    filled = re.sub(r'\{(\w+)\}', fill, text)
    return None if missing else filled


def _printed(entry, field_id):
    field = entry.field(field_id)
    return field is not None and field['kind'] not in UNPRINTED


def _list_length(section):
    """How many items a list block draws from a section: its items with text, else its body's lines (R1's list)."""
    items = [item for item in (section or {}).get('items') or [] if isinstance(item, dict)
             and any(str(item.get(key) or '').strip() for key in ('label', 'text', 'value'))]
    return len(items) or len([line for line in str((section or {}).get('body') or '').split('\n') if line.strip()])


def _label_key(place, labels):
    """The label a placement prints by its `label` param, or None.

    A list of several items prints its plural as R1's list block does: the
    `label_many` key, else the key with an s, when the template holds it.
    So an English list of two enclosures reads "Enclosures:", not "Enclosure:".
    """
    params = place.params or {}
    key = params.get('label')
    if not isinstance(key, str) or key not in labels:
        return None
    if place.block == 'list' and _list_length(place.section) > 1:
        many = params.get('label_many') or f'{key}s'
        if isinstance(many, str) and many in labels:
            return many
    return key


def _header_facts(ctx, sheet):
    """The running header's facts a reader can find: the header is cut at a word to fit, so only those that fit."""
    values = [value for value in (ctx.fact(name) for name in ctx.template['furniture'].get('header') or ())
              if value is not None]
    if not values:
        return []
    left, bottom, width, height = sheet.geometry(ctx.template)
    # The step-0 type is the largest, so what fits here fits on a paper drawn at any later step.
    size = min(sheet.FURNITURE_SIZE, ctx.styles['small'].fontSize)
    shown = normal(sheet._cut(sheet.header_text(ctx), ctx.face, size, width))
    return [value for value in values if normal(ctx.plain(value)) in shown]


def expect_for(artifact, content, *, entry, template, locale, pages, cues=frozenset(), day=None):
    """What `problems` holds the paper render_paper drew to: its frames, page rule, facts, labels, language, codes.

    The facts are the verified values (and clock values) of the printable
    fields that a placement whose `when` holds draws, by its `fields`, a
    label slot or the running header of a paper longer than a page (those the
    header has room for: it is cut at a word to fit). The labels are the
    `label` parameter of each such placement, its slots filled, in the plural
    for a list of several items; one whose slot has no fact is left out, since
    a block may drop that sentence (`drop_empty_slots`). Captions and the
    other labels a block picks by itself are not required: whether they print
    depends on the block.

    When a placement that holds starts a page, the last page may be that part
    alone (a test's answer key): its fill is not judged.
    """
    from . import page as sheet
    from .ctx import Ctx, _has_text, holds, places
    raw = template
    metadata = artifact.get('metadata') or {}
    locale = locale if locale in LOCALES else 'en'
    left, bottom, width, height = sheet.geometry(raw)
    ctx = Ctx(content=content, entry=entry, template=raw, locale=locale, step=0, pages=pages, width=width,
              frame_height=height, cues=frozenset(cues or ()), day=day)
    labels = raw.get('labels') or {}
    facts, words, stub, gutter = [], [], STUB_MIN, 0.0
    for place in places(ctx):
        if not holds(place.when, ctx, place):
            continue
        if place.page_break_before:
            stub = 0
        if (place.params or {}).get('gutter'):
            gutter = GUTTER_EMS * ctx.size
        for field_id in place.fields:
            value = ctx.fact(field_id)
            if value is not None and _printed(entry, field_id):
                # A signer written "post | name" prints as two cells, so each side is read back on its own.
                facts += [piece.strip() for line in value.split('\n') for piece in line.split('|')
                          if piece.strip()] if '|' in value else [value]
        key = _label_key(place, labels)
        any_part = (place.params or {}).get('any_part')
        if isinstance(any_part, list) and not any(_has_text(ctx.section(part_id)) for part_id in any_part
                                                  if isinstance(part_id, str)):
            # A chapter word over optional parts is drawn only when one of them has text (the heading block's
            # any_part): a two-page business plan has no operations chapter to look for.
            key = None
        if key is not None:
            text = labels[key].get(locale) or labels[key].get('en', '')
            filled = _filled(text, ctx)
            if filled is not None and filled.strip():
                words.append(filled.strip())
    if (artifact.get('page_count') or 0) > 1 and raw['furniture'].get('later') == 'header_number':
        facts += _header_facts(ctx, sheet)
    return {
        'frames': metadata.get('frames'), 'furniture': metadata.get('furniture'),
        'rule': raw['page_rule'].get('kind', 'flow'), 'rule_pages': raw['page_rule'].get('pages'),
        'quoted': pages + int(metadata.get('uncounted') or 0), 'longer': LONGER in (metadata.get('warnings') or ()),
        'facts': list(dict.fromkeys(facts)), 'labels': list(dict.fromkeys(words)), 'locale': locale,
        'stub_min': stub, 'warnings': list(metadata.get('warnings') or ()), 'gutter': gutter,
    }

