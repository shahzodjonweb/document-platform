"""A CV's content as a one- or two-page A4 PDF in its template.

The content is the ordinary document shape (`title` = the person's name, eight
sections with fixed ids, entries as `items`), written by the model from the
customer's own facts. The renderer's job is to make it look finished whatever
the model wrote:

* **It never fails on content.** Leading bullet characters are stripped (the
  renderer draws its own), arrows and comparison signs the faces lack are
  written as text (→ as –, ≈ as ~, ≥ as >=), other characters no bundled face
  can draw are left out and recorded (`metadata['dropped_chars']`), an entry
  that was cut at a length cap loses its trailing partial word instead of
  ending mid-word, and the contacts are held to twelve of 160 characters.
  A build that ReportLab cannot lay out at one setting is tried at a tighter
  one, as a CV too long for it is.
* **The page count is the renderer's, not the model's.** A CV is one page when
  it fits at a comfortable size and two when it does not (`fit`): a roomy
  two-pager reads better than a cramped one-pager. Only when even the tightest
  readable setting needs a third page are the least important lines cut, in a
  fixed order, and names, contacts, dates, employers, education and languages
  are never among them.
* **Headings are ours.** The six fixed sections print their headings in the
  CV's language; only the `extra` section may carry the model's own.
"""
import io
import re
import unicodedata
from pathlib import Path

from apps.core.errors import DomainError

from . import fonts, templates
from .layouts import ORDER, SIDE, Sheet

MAX_PAGES = 2
# A page 2 with less than this many characters looks like an accident; the fit
# avoids it (`check.py` reports it).
WIDOW_CHARS = 300
# The renderer cuts nothing until the tightest step still needs a third page.
TIGHTEST = 4
CONTACT_KEYS = ('phone', 'email', 'location', 'telegram', 'linkedin', 'website', 'github', 'birth', 'age')
# Lengths at which `validate_content` and the CV clean cut a field. A field
# exactly this long was probably cut, and probably mid-word. A CV's entries are
# always held to 900 (cv/content.py LIMITS): a slide item's 600 is no cut here,
# and a role written to 600 characters keeps its last word.
CAPS = {'title': (160,), 'heading': (160,), 'label': (160,), 'value': (160,), 'text': (900,)}
# How many contacts a CV shows, and how long each may be: more of them, or one
# longer, would run off a sidebar or fill a header.
MAX_CONTACTS, CONTACT_CHARS = 12, 160
# Signs a model or a customer writes that the faces cannot draw, as the text
# that says the same: "с 10 → 15 млрд" must not become "с 10 15 млрд".
SUBSTITUTES = {'→': '–', '⇒': '–', '⟶': '–', '➔': '–', '➝': '–', '↔': '–', '≈': '~', '∼': '~', '≃': '~',
               '≥': '>=', '⩾': '>=', '≤': '<=', '⩽': '<=', '≠': '!='}

HEADINGS = {
    'en': {'profile': 'Profile', 'experience': 'Experience', 'education': 'Education', 'skills': 'Skills',
           'languages': 'Languages', 'projects': 'Projects', 'certificates': 'Certificates',
           'extra': 'Additional', 'contact': 'Contact'},
    'uz': {'profile': 'Profil', 'experience': 'Ish tajribasi', 'education': 'Taʼlim', 'skills': 'Ko‘nikmalar',
           'languages': 'Tillar', 'projects': 'Loyihalar', 'certificates': 'Sertifikatlar',
           'extra': 'Qo‘shimcha', 'contact': 'Aloqa'},
    'ru': {'profile': 'Профиль', 'experience': 'Опыт работы', 'education': 'Образование', 'skills': 'Навыки',
           'languages': 'Языки', 'projects': 'Проекты', 'certificates': 'Сертификаты',
           'extra': 'Дополнительно', 'contact': 'Контакты'},
}
CONTACT_LABELS = {
    'en': {'phone': 'Phone', 'email': 'Email', 'location': 'Location', 'telegram': 'Telegram',
           'linkedin': 'LinkedIn', 'website': 'Website', 'github': 'GitHub', 'birth': 'Date of birth',
           'age': 'Age'},
    'uz': {'phone': 'Telefon', 'email': 'Email', 'location': 'Manzil', 'telegram': 'Telegram',
           'linkedin': 'LinkedIn', 'website': 'Veb-sayt', 'github': 'GitHub', 'birth': 'Tug‘ilgan sana',
           'age': 'Yosh'},
    'ru': {'phone': 'Телефон', 'email': 'Эл. почта', 'location': 'Город', 'telegram': 'Telegram',
           'linkedin': 'LinkedIn', 'website': 'Сайт', 'github': 'GitHub', 'birth': 'Дата рождения',
           'age': 'Возраст'},
}
# What a model may write instead of a contact key.
CONTACT_WORDS = {
    'phone': ('tel', 'telephone', 'mobile', 'cell', 'telefon', 'телефон', 'тел'),
    'email': ('e-mail', 'mail', 'почта', 'эл. почта', 'pochta', 'elektron pochta'),
    'location': ('city', 'address', 'manzil', 'shahar', 'город', 'адрес'),
    'telegram': ('tg', 'телеграм'),
    'website': ('site', 'web', 'portfolio', 'veb-sayt', 'sayt', 'сайт'),
    'birth': ('birthday', 'date of birth', 'dob', 'tug‘ilgan sana', "tug'ilgan sana", 'дата рождения'),
    'age': ('yosh', 'yoshi', 'возраст'),
}
# A bullet a model or a customer typed: a bullet sign, or a dash or star with a space after it.
BULLET = re.compile(r'^\s*(?:[•·▪◦‣●○■□]\s*|[*\-–—]\s+)')
SENTENCE = re.compile(r'(?<=[.!?…])\s+')


def _contact_key(label):
    key = ' '.join(str(label or '').strip().lower().replace('ʻ', '‘').split())
    if key in CONTACT_KEYS:
        return key
    for name, words in CONTACT_WORDS.items():
        if key in words:
            return name
    return key


class _Cleaner:
    """Text as the faces can draw it, with what had to be left out remembered."""

    def __init__(self, allowed):
        self.allowed, self.dropped = allowed, set()

    def __call__(self, value, caps=()):
        raw = str(value or '')
        cut = bool(caps) and len(raw.strip()) in caps
        text = unicodedata.normalize('NFC', raw.replace('\r\n', '\n').replace('\r', '\n'))
        kept = []
        for char in text:
            if char == '\n':
                kept.append(char)
            elif char.isspace():
                kept.append(' ')
            elif ord(char) in self.allowed:
                kept.append(char)
            elif char in SUBSTITUTES and all(ord(sub) in self.allowed for sub in SUBSTITUTES[char]):
                kept.append(SUBSTITUTES[char])
            else:
                self.dropped.add(char)
        text = '\n'.join(' '.join(line.split()) for line in ''.join(kept).split('\n')).strip()
        return _uncut(text) if cut else text


def _uncut(text):
    """A field cut at its cap, without the partial word at its end."""
    if not text or text[-1] in '.!?…)»"' or ' ' not in text[-60:]:
        return text
    return text[:text.rfind(' ')].rstrip(' ,;:–—-·/(')


def _bounded(text, limit):
    """`text` at most `limit` characters, cut after a whole word when it has to be cut."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if ' ' in cut:
        cut = cut[:cut.rfind(' ')]
    return cut.rstrip(' ,;:–—-·/(')


def _lines(text):
    lines = []
    for line in str(text or '').split('\n'):
        line = BULLET.sub('', line).strip()
        if line:
            lines.append(line)
    return lines


def prepare(content, locale='en', look=None):
    """The CV as the drawers read it, and the characters that were left out.

    {'name', 'headline', 'contacts': [(key, label, value)], 'labels': {...},
     'sections': [{'id', 'heading', 'lines', 'items': [{'label', 'value', 'lines'}]}]}
    in reading order, empty sections left out.
    """
    locale = locale if locale in HEADINGS else 'en'
    look = look or templates.look({})
    heading_face, body_face = templates.FONT_PAIRS[look['fonts']]
    clean = _Cleaner(fonts.coverage(heading_face) & fonts.coverage(body_face))
    headings, contact_labels = HEADINGS[locale], CONTACT_LABELS[locale]
    content = content if isinstance(content, dict) else {}
    raw_sections = [section for section in content.get('sections') or [] if isinstance(section, dict)]
    by_id = {}
    for section in raw_sections:
        by_id.setdefault(str(section.get('id') or ''), section)
    profile = by_id.get('profile', {})
    contacts = []
    for item in profile.get('items') or []:
        if not isinstance(item, dict):
            continue
        key = _contact_key(clean(item.get('label'), CAPS['label']))
        value = clean(item.get('text') or item.get('value'), CAPS['text'])
        value = _bounded(' '.join(value.split()), CONTACT_CHARS)
        if not value:
            continue
        label = contact_labels.get(key) or str(item.get('label') or '').strip()[:40] or key
        contacts.append((key, label, value))
    rank = {key: index for index, key in enumerate(CONTACT_KEYS)}
    contacts.sort(key=lambda contact: rank.get(contact[0], len(CONTACT_KEYS)))
    contacts = contacts[:MAX_CONTACTS]
    sections = []
    summary = _lines(clean(profile.get('body')))
    if summary:
        sections.append({'id': 'profile', 'heading': headings['profile'], 'lines': summary, 'items': []})
    for section in raw_sections:
        sid = str(section.get('id') or '')
        if sid == 'profile' or by_id.get(sid) is not section:
            continue
        items = []
        for item in section.get('items') or []:
            if not isinstance(item, dict):
                continue
            entry = {'label': clean(item.get('label'), CAPS['label']), 'value': clean(item.get('value'), CAPS['value']),
                     'lines': _lines(clean(item.get('text'), CAPS['text']))}
            if sid in ('skills', 'languages'):
                entry['lines'] = [', '.join(entry['lines'])] if entry['lines'] else []
            if entry['label'] or entry['lines'] or entry['value']:
                items.append(entry)
        own = clean(section.get('heading'), CAPS['heading'])
        body = _lines(clean(section.get('body')))
        if body and sid not in SIDE:
            # A section the model wrote as prose instead of entries still reads.
            items = [{'label': '', 'value': '', 'lines': body}] + items
        if not items:
            continue
        if sid in headings and sid != 'extra':
            heading = headings[sid]
        else:
            heading = own or headings['extra']
        sections.append({'id': sid if sid in ORDER else f'other:{sid}', 'heading': heading, 'lines': [],
                         'items': items})
    rank = {key: index for index, key in enumerate(ORDER)}
    sections.sort(key=lambda section: rank.get(section['id'], len(ORDER)))
    cv = {'name': ' '.join(clean(content.get('title'), CAPS['title']).split()),
          'headline': ' '.join(clean(profile.get('heading'), CAPS['heading']).split()),
          'contacts': contacts, 'labels': headings, 'sections': sections}
    return cv, sorted(clean.dropped)


# ------------------------------------------------------------------ trimming

def _copy(cv):
    return {**cv, 'sections': [{**section, 'lines': list(section['lines']),
                                'items': [{**item, 'lines': list(item['lines'])} for item in section['items']]}
                               for section in cv['sections']]}


def _find(cv, sid):
    return next((section for section in cv['sections'] if section['id'] == sid), None)


def trim_sequence(cv):
    """Ever shorter versions of the CV, one cut at a time, least important first: (code, cv).

    Extra entries from the last, projects from the last, certificates down to
    three; then round after round over the roles from the oldest, taking each
    one's last achievement line while it keeps more than two lines; the
    profile from its last sentence down to one; every skill group to its first
    eight. Only then do the oldest roles lose their last achievement too,
    keeping their organisation line, and a profile that is one endless
    sentence its words after the sixtieth. Never cut: the name, headline,
    contacts, dates, organisation lines, education and languages.
    """
    state = _copy(cv)

    def cut(change, code):
        nonlocal state
        state = _copy(state)
        change(state)
        return code, state

    def pop_entry(sid):
        def change(current):
            section = _find(current, sid)
            section['items'].pop()
            if not section['items']:
                current['sections'].remove(section)
        return change

    def rounds(keep):
        while True:
            experience = _find(state, 'experience')
            items = experience['items'] if experience else []
            longer = [index for index in reversed(range(len(items))) if len(items[index]['lines']) > keep]
            if not longer:
                return
            for index in longer:
                yield cut(lambda current, index=index: _find(current, 'experience')['items'][index]['lines'].pop(),
                          'roles')

    added = [section['id'] for section in cv['sections'] if section['id'] == 'extra' or section['id'].startswith('other:')]
    for sid in [*reversed(added), 'projects']:
        while _find(state, sid):
            yield cut(pop_entry(sid), 'projects' if sid == 'projects' else 'extra')
    while _find(state, 'certificates') and len(_find(state, 'certificates')['items']) > 3:
        yield cut(pop_entry('certificates'), 'certificates')
    yield from rounds(2)
    while _find(state, 'profile'):
        sentences = [piece for line in _find(state, 'profile')['lines'] for piece in SENTENCE.split(line) if piece]
        if len(sentences) <= 1:
            break
        yield cut(lambda current, kept=sentences[:-1]: _find(current, 'profile').update(lines=[' '.join(kept)]),
                  'profile')
    skills = _find(state, 'skills')
    for index in range(len(skills['items']) if skills else 0):
        words = [word.strip() for word in ', '.join(_find(state, 'skills')['items'][index]['lines']).split(',')
                 if word.strip()]
        if len(words) > 8:
            yield cut(lambda current, index=index, words=words:
                      _find(current, 'skills')['items'][index].update(lines=[', '.join(words[:8])]), 'skills')
    yield from rounds(1)
    # Last, a profile that is one endless sentence keeps its first sixty words.
    profile = _find(state, 'profile')
    words = ' '.join(profile['lines']).split() if profile else []
    if len(words) > 60:
        yield cut(lambda current: _find(current, 'profile').update(lines=[' '.join(words[:60]).rstrip(',;:') + '.']),
                  'profile')


# ------------------------------------------------------------------ fitting

class Attempt:
    def __init__(self, sheet, data, pages, tail):
        self.sheet, self.data, self.pages, self.tail = sheet, data, pages, tail


def _build(cv, look, step, photo, meta, breaks=0, balance=None):
    """One real build. One ReportLab cannot lay out (a paragraph taller than a page) counts as too long."""
    from pypdf import PdfReader
    from reportlab.platypus.doctemplate import LayoutError
    buffer = io.BytesIO()
    try:
        sheet = Sheet(cv, look, step, photo, breaks=breaks, balance=balance, **meta).build(buffer)
    except LayoutError:
        return Attempt(None, b'', MAX_PAGES + 1, None)
    data = buffer.getvalue()
    reader = PdfReader(io.BytesIO(data))
    pages = len(reader.pages)
    tail = len(re.sub(r'\s', '', reader.pages[1].extract_text() or '')) if pages == 2 else None
    return Attempt(sheet, data, pages, tail)


def fit(cv, look, photo=None, meta=None):
    """The loosest setting that gives one comfortable page, else two, else the fewest cuts.

    Returns (attempt, step, cv, trimmed codes). Every attempt is a real build,
    side-column measuring and group moves included, so the page count is honest.
    A compact CV's second page is then balanced across its two columns.
    """
    meta = meta or {}
    attempt, step, used, codes, breaks = _fit(cv, look, photo, meta)
    if look['drawer'] == 'compact' and attempt.pages == 2:
        attempt = _balanced(attempt, used, look, step, photo, meta, breaks)
    return attempt, step, used, codes


def _balanced(attempt, cv, look, step, photo, meta, breaks):
    """The same two-page compact CV with page 2's text shared between its columns, not all in the first."""
    from .layouts import H, MM
    top = H - 14 * MM
    used = [top - attempt.sheet.reach.get((2, name), top) for name in ('c0', 'c1')]
    if used[1] > 0 and abs(used[0] - used[1]) < 48:
        return attempt
    target = sum(used) / 2 + 16
    for _ in range(8):
        trial = _build(cv, look, step, photo, meta, breaks, balance=target)
        if trial.pages == 2 and trial.tail >= WIDOW_CHARS:
            return trial
        target += 24
    return attempt


def _fit(cv, look, photo, meta):
    first = 1 if look['drawer'] == 'compact' else 0
    built = {}

    def at(step):
        if step not in built:
            built[step] = _build(cv, look, step, photo, meta)
        return built[step]

    for step in range(first, min(first + 3, TIGHTEST + 1)):
        if at(step).pages == 1:
            return at(step), step, cv, [], 0
    for step in range(first, TIGHTEST + 1):
        attempt = at(step)
        if attempt.pages > MAX_PAGES:
            continue
        if attempt.pages == 2 and attempt.tail < WIDOW_CHARS:
            # A few lines alone on page 2: one page at a tighter step, else whole
            # sections moved over so page 2 is worth turning to.
            for tighter in range(step + 1, TIGHTEST + 1):
                if at(tighter).pages == 1:
                    return at(tighter), tighter, cv, [], 0
            for breaks in (1, 2, 3):
                moved = _build(cv, look, step, photo, meta, breaks)
                if moved.pages == 2 and moved.tail >= WIDOW_CHARS:
                    return moved, step, cv, [], breaks
        return attempt, step, cv, [], 0
    states = list(trim_sequence(cv))
    low, high, found = 0, len(states) - 1, None
    while low <= high:
        middle = (low + high) // 2
        attempt = _build(states[middle][1], look, TIGHTEST, photo, meta)
        if attempt.pages <= MAX_PAGES:
            found, high = (middle, attempt), middle - 1
        else:
            low = middle + 1
    if found is None:
        raise DomainError('invalid_output')
    index, attempt = found
    codes = []
    for code, _ in states[:index + 1]:
        if code not in codes:
            codes.append(code)
    return attempt, TIGHTEST, states[index][1], codes, 0


def _portrait(portrait):
    """The portrait as the drawers place it, from placed bytes, raw bytes or nothing."""
    if not portrait:
        return None, []
    if isinstance(portrait, dict) and portrait.get('jpeg'):
        return portrait, []
    if isinstance(portrait, (bytes, bytearray)):
        from .portrait import square
        placed = square(bytes(portrait))
        return (placed, []) if placed else (None, ['cv_photo_unusable'])
    return None, ['cv_photo_unusable']


def render_cv(content, path, locale='en', style=None, portrait=None):
    """Render `content` to `path` in the template `style` names; returns what was made.

    `portrait` is the placed photo from `portrait.load` (or raw image bytes); a
    template without a photo slot leaves it out and says so (`cv_photo_no_slot`),
    so the customer who sent one is told why it is not there. The result has
    `render_pdf`'s shape.
    """
    path = Path(path)
    look = templates.look(style)
    photo, warnings = _portrait(portrait) if look['photo'] else (None, ['cv_photo_no_slot'] if portrait else [])
    cv, dropped = prepare(content, locale, look)
    name = cv['name']
    meta = {'title': f'{name} — CV' if name else 'CV', 'author': name, 'subject': cv['headline'],
            'locale': locale if locale in HEADINGS else 'en'}
    attempt, step, used, trimmed = fit(cv, look, photo, meta)
    path.write_bytes(attempt.data)
    frames = {page: attempt.sheet.frames['first' if page == 1 else 'later'] for page in range(1, attempt.pages + 1)}
    return {'path': str(path), 'name': path.name, 'mime_type': 'application/pdf', 'page_count': attempt.pages,
            'role': 'user_document', 'shortened': bool(trimmed),
            'metadata': {'design': look['id'], 'layouts': [look['drawer']], 'fit_step': step, 'trimmed': trimmed,
                         'frames': frames, 'dropped_chars': dropped, 'sidebar_moved': list(attempt.sheet.moved),
                         'portrait': bool(photo), 'warnings': warnings}}


def filename(content):
    """'<name> CV.pdf': the person's name in letters, digits, spaces and name punctuation, at most 60 characters."""
    name = str((content or {}).get('title') or '')
    clean = ''.join(char for char in unicodedata.normalize('NFC', name) if char.isalnum() or char in " -'’‘ʼ.")
    clean = ' '.join(clean.split())
    if len(clean) > 53:
        clean = clean[:53].rsplit(' ', 1)[0] if ' ' in clean[:53] else clean[:53]
    clean = clean.strip(' .-')
    return f'{clean} CV.pdf' if clean else 'CV.pdf'
