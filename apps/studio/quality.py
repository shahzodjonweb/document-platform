"""Checks on a whole generated document, and the one repair they may ask for.

The prompt asks for the right language, topic and shape; this checks the
compiled result, because the model does not always deliver what it is asked
and a long document is written in several calls that cannot see each other's
mistakes. Everything here is deterministic and cheap. What can be put right
without the model is put right (alphabet, stray markdown, a continuing page's
repeated heading); what cannot — a passage plainly in the wrong language, an
empty section, a slide that repeats another — is sent back to the model once,
for those sections only (`repair`), and the rest of the document is kept as it
was. A change to selected pages never touches the others, not even to tidy them.

Only codes, counts and section ids are ever logged: never the customer's text.
"""
import copy
import logging
import re
import time
from dataclasses import dataclass, field

from . import language, scripts, topics

logger = logging.getLogger(__name__)

# A repair is one call per ten sections; past this many it is a new document,
# not a repair, and the time it would take is not in the job's lease.
REPAIR_MAX_SECTIONS = 30
# A repair is started only with this long left, per batch of ten sections.
REPAIR_SECONDS_PER_CALL = 100
DUPLICATE_SECTION = 0.6
DUPLICATE_PARAGRAPH = 0.8
PARAGRAPH_WORDS = 10


@dataclass
class Report:
    # code -> [section ids] (or field paths for 'script'). Only the codes in
    # to_repair() go to the model; foreign_passage, off_topic and
    # continued_heading are recorded (the last is put right in finish()).
    issues: dict = field(default_factory=dict)
    missing_subtopics: list = field(default_factory=list)

    def add(self, code, item):
        bucket = self.issues.setdefault(code, [])
        if item not in bucket:
            bucket.append(item)

    def ids(self, *codes):
        return [item for code in codes for item in self.issues.get(code, [])]

    def to_repair(self):
        """Section ids that only the model can put right (repair() puts them in document order)."""
        return list(dict.fromkeys(self.ids('wrong_language', 'empty_section', 'duplicate_section',
                                           'duplicate_paragraph', 'repeated_heading')))

    def summary(self):
        """Codes and counts only — safe to log."""
        counts = {code: len(items) for code, items in self.issues.items() if items}
        if self.missing_subtopics:
            counts['missing_subtopic'] = len(self.missing_subtopics)
        return counts


# --- Text helpers ---------------------------------------------------------------

def _words(text):
    return re.findall(r"[\wЀ-ӿ']+", language.normalised(text or '').lower())


def _shingles(words, size):
    if len(words) < size:
        return {tuple(words)} if words else set()
    return {tuple(words[i:i + size]) for i in range(len(words) - size + 1)}


def _similar(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def section_text(section, *, notes=False):
    parts = [section.get('heading', ''), section.get('body', '')]
    for item in section.get('items') or []:
        parts.extend(str(item.get(key, '')) for key in ('label', 'text', 'value'))
    parts.extend(section.get('columns') or [])
    if notes:
        parts.append(section.get('notes', ''))
    return '\n'.join(part for part in parts if part)


def document_text(content):
    return '\n'.join([content.get('title', '')] + [section_text(s, notes=True) for s in content.get('sections', [])])


def _paragraphs(section):
    lines = [line for line in (section.get('body') or '').split('\n') if line.strip()]
    lines += [str(item.get('text', '')) for item in section.get('items') or [] if item.get('text')]
    return [line for line in lines if len(_words(line)) >= PARAGRAPH_WORDS]


# --- Deterministic tidying --------------------------------------------------------

# Only what cannot be the text itself is taken out. '__' is never emphasis
# here: blanks to fill in (She ____ to school), __init__ and __name__ are text.
# '**' is bold only with no letter or '*' just outside it: x**2 + y**2 is a sum.
MARKDOWN_BOLD = re.compile(r'(?<![\w*])\*\*(?=\S)(.+?)(?<=\S)\*\*(?![\w*])')
# '## ' starts a heading; a single '# ' only before a capital on a short line,
# because '# of students' and a code comment are text.
MARKDOWN_HEADING = re.compile(r' {0,3}(#{1,6})[ \t]+(?=\S)')
# A matched pair of the simple tags a model writes; 'a<b and c>d', '0<p<1' and
# 'the HTML <p> tag' are text and stay.
HTML_PAIR = re.compile(r'<(b|i|u|em|strong)>(.*?)</\1>', re.IGNORECASE)
HTML_BREAK = re.compile(r'<br\s*/?>', re.IGNORECASE)
CONTROL = re.compile('[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F\uFFFD\u200B\u2060\uFEFF]')


def _tidy_line(line):
    line = line.rstrip()
    heading = MARKDOWN_HEADING.match(line)
    if heading:
        rest = line[heading.end():]
        if len(heading.group(1)) >= 2 or (len(line) < 100 and rest[:1].isupper()):
            line = rest
    return line


def tidy_text(text):
    """Text without the marks a model leaves behind: markdown, tags, control characters.

    Spacing, indentation and anything that could be the text itself are kept:
    a code sample, a fill-in-the-blank exercise or a formula comes out as written.
    """
    if not isinstance(text, str) or not text:
        return text
    value = HTML_BREAK.sub('\n', CONTROL.sub('', text))
    while True:
        unpaired = HTML_PAIR.sub(r'\2', value)
        if unpaired == value:
            break
        value = unpaired
    value = MARKDOWN_BOLD.sub(r'\1', value)
    return '\n'.join(_tidy_line(line) for line in value.split('\n'))


def _within(content, selected, fix):
    """`fix(content)`, applied to the selected sections alone when there is a selection.

    A change to selected pages leaves the others, the title and the questions
    exactly as they were — they are the customer's, and the check that the
    change kept them compares them byte for byte.
    """
    if not selected:
        return fix(content)
    part = {'title': '', 'sections': [s for s in content['sections'] if s.get('id') in selected], 'questions': []}
    done, paths = fix(part)
    fixed = {s['id']: s for s in done['sections']}
    return {**content, 'sections': [fixed.get(s.get('id'), s) for s in content['sections']]}, paths


def _tidy(content):
    result = copy.deepcopy(content)
    changed = []
    for path, text in list(scripts.fields(result)):
        value = tidy_text(text)
        if value != text:
            scripts._set(result, path, value)
            changed.append(path)
    return result, changed


def tidy(content, selected=None):
    """(content with every visible field tidied, paths that changed)."""
    return _within(content, selected, _tidy)


def enforce(content, locale, selected=None):
    """scripts.enforce, on the selected sections alone when there is a selection."""
    return _within(content, selected, lambda part: scripts.enforce(part, locale))


# --- Checking -------------------------------------------------------------------

# A whole word only: "rus tili", "ruscha" and "русский" name Russian, while
# "Rustam", "Ruslan" and "Gold Rush" do not; "O‘zbekiston" is a country.
NAMED_LANGUAGES = {
    'en': r"ingi?liz\w*|english|англи\w*|инглиз\w*",
    'ru': r"rus(?:cha\w*)?|russian\w*|русск\w*|рус(?:ча\w*)?",
    'uz': r"o'?zbek(?:cha\w*)?|uzbek|узбекск\w*|узбек(?:ча\w*)?|ўзбек(?:ча\w*)?",
}
# Code is in no language: a Python or SQL sample on a Russian or Uzbek page is
# left out when the page's language is judged.
CODE_LINE = re.compile(r"^\s|:\s*$|[=(){}\[\];]|\b(?:SELECT|FROM|WHERE|INSERT|UPDATE)\b"
                       r"|\b(?:def|class|import|return|print|function|const)\b")
# A cover, section divider or closing slide is meant to repeat the deck's title
# and subtitle or to say the same "Questions?" as another; it is not compared.
STRUCTURAL = ('cover', 'closing', 'section')


def _languages_named(text):
    """Languages the brief or the change request names: their passages may be content (an English lesson)."""
    body = language.normalised(text)
    return {code for code, words in NAMED_LANGUAGES.items()
            if re.search(r"(?<![\wЀ-ӿ'])(?:" + words + r")(?![\wЀ-ӿ'])", body, re.IGNORECASE)}


def _prose(text):
    return '\n'.join(line for line in text.split('\n') if line.strip() and not CODE_LINE.search(line))


def _flag(report, code, sid, earlier, mine):
    """Of two sections that repeat each other the later is rewritten, unless only the earlier may change."""
    if mine(sid):
        report.add(code, sid)
    elif mine(earlier):
        report.add(code, earlier)


def check(content, *, locale, fmt, prompt='', request=None, selected=None, expected=None, subtopics=None):
    """A Report on `content`, the model's answer before any correction.

    `prompt` is the original brief; `request` is a revision's change request
    (None when this is not a revision). With `selected`, every section is still
    compared — a selected slide may copy one the change left alone — but only
    the selected ones are reported.
    """
    report = Report()
    sections = content.get('sections', [])
    mine = (lambda sid: sid in selected) if selected else (lambda sid: True)
    for path in scripts.violations(content, locale):
        if not selected or (path[0] == 'sections' and mine(sections[path[1]].get('id'))):
            report.add('script', path)
    if expected is not None and len(sections) != expected:
        report.add('section_count', len(sections))
    # A passage is sent back for its language only when the mistake is plain:
    # the model wrote in the language the brief is written in instead of the
    # one asked for, or wrote Russian in an Uzbek or English document whose
    # brief and change request never name Russian. An English example in an
    # Uzbek lesson, a quoted book title or a code sample is content, and is
    # recorded as foreign_passage, never rewritten.
    brief = 'ru' if language.written_in_russian(prompt) else language.written_in(prompt, least_words=4)
    named = _languages_named(prompt + '\n' + (request or ''))
    wrong, judged = [], 0
    headings, compared, paragraphs = {}, [], []
    current = ''  # the heading over the page being read: a continuing page has none of its own
    for section in sections:
        sid = section.get('id')
        text = section_text(section)
        if not text.strip():
            if mine(sid):
                report.add('empty_section', sid)
            continue
        bare = not (section.get('body') or '').strip() and not section.get('items')
        if mine(sid):
            # A document's continuing page has no heading but must have text.
            if fmt != 'pptx' and bare:
                report.add('empty_section', sid)
            if section.get('layout') != 'quote':
                judged += 1
                written = language.written_in(_prose(section_text(section, notes=True)))
                if written and written != locale:
                    if written == brief or (written == 'ru' and 'ru' not in named):
                        wrong.append(sid)
                    else:
                        report.add('foreign_passage', sid)
        counted = not bare and section.get('layout') not in STRUCTURAL
        heading = ' '.join(_words(section.get('heading', '')))
        if heading and fmt != 'pptx' and heading == current:
            # The page goes on with the topic of the one before: finish() empties its heading.
            if mine(sid):
                report.add('continued_heading', sid)
        elif heading and counted:
            first = headings.setdefault(heading, sid)
            if first != sid:
                _flag(report, 'repeated_heading', sid, first, mine)
        current = heading or current
        if counted:
            words = _words(text)
            shingles = _shingles(words, 3 if len(words) >= 12 else 2)
            if len(words) >= 6:
                earlier = next((owner for owner, seen in compared if _similar(shingles, seen) >= DUPLICATE_SECTION),
                               None)
                if earlier:
                    _flag(report, 'duplicate_section', sid, earlier, mine)
            compared.append((sid, shingles))
        grams = [_shingles(_words(paragraph), 4) for paragraph in _paragraphs(section)
                 if section.get('layout') not in STRUCTURAL]
        for gram in grams:
            earlier = next((owner for owner, seen in paragraphs
                            if owner != sid and _similar(gram, seen) >= DUPLICATE_PARAGRAPH), None)
            if earlier:
                _flag(report, 'duplicate_paragraph', sid, earlier, mine)
        paragraphs.extend((sid, gram) for gram in grams)
    # Most of a revised document in another language is a translation the
    # change request asked for in words the language reader missed: kept.
    translated = request is not None and len(wrong) * 2 > judged
    for sid in wrong:
        report.add('foreign_passage' if translated else 'wrong_language', sid)
    # Subtopics are compared word by word, so only when the description is in
    # the language the document is written in.
    subtopics = topics.required(prompt) if subtopics is None else subtopics
    if subtopics and brief == locale:
        report.missing_subtopics = topics.missing(subtopics, document_text(content))
    # Off-topic is a signal, not a verdict: recorded, never repaired.
    anchor = topics.stems(prompt) | topics.stems(content.get('title', ''))
    if anchor and brief == locale and len(sections) >= 3:
        for section in sections:
            body = section_text(section)
            if mine(section.get('id')) and len(_words(body)) >= 25 and not topics.overlap(topics.stems(body), anchor):
                report.add('off_topic', section.get('id'))
    return report


# --- Repairing ------------------------------------------------------------------

def request_text(report, locale, fmt, ids):
    """The change request a repair call is given: what is wrong, by section."""
    name = language.NAMES[locale]
    alphabet = 'Latin' if language.SCRIPTS[locale] == 'latin' else 'Cyrillic'
    unit = 'slide' if fmt == 'pptx' else 'page'
    lines = [f'Quality repair of the {unit}s with these ids: {", ".join(ids)}. Change only these {unit}s, and in '
             f'each only what its line below asks for; keep the rest word for word. document_context shows the '
             f'whole document, which stays as it is. Write every rewritten {unit} entirely in {name}, {alphabet} '
             f'alphabet, on the exact topic of the original brief.']
    pick = lambda code: [i for i in report.issues.get(code, []) if i in ids]
    if pick('wrong_language'):
        lines.append(f'{", ".join(pick("wrong_language"))}: written in the wrong language. Rewrite each completely '
                     f'in {name}, keeping its meaning, its role in the document, its layout and its length.')
    if pick('empty_section'):
        lines.append(f'{", ".join(pick("empty_section"))}: empty. Write each as the {unit} that belongs at this '
                     f'point of the document, following writing_guidance (heading, text and, for a slide, speaker '
                     f'notes).')
    repeated = list(dict.fromkeys(pick('duplicate_section') + pick('duplicate_paragraph')))
    if repeated:
        extra = ''
        if report.missing_subtopics:
            extra = (' Prefer subtopics the brief asks for that the document does not cover yet: '
                     + '; '.join(report.missing_subtopics) + '.')
        lines.append(f'{", ".join(repeated)}: repeat what other {unit}s already say. Replace the repeated content '
                     f'with new, specific information on the topic that no other {unit} gives, keeping the layout '
                     f'type and the length.{extra}')
    if pick('repeated_heading') and fmt == 'pptx':
        lines.append(f'{", ".join(pick("repeated_heading"))}: the heading repeats an earlier one. Give each a '
                     f'heading that names what this slide adds. Change nothing else.')
    elif pick('repeated_heading'):
        # A page that goes on with the topic before it has no heading of its own.
        lines.append(f'{", ".join(pick("repeated_heading"))}: the heading repeats an earlier one. If the page '
                     f'continues the topic of the page before it, return an empty heading; otherwise give it a '
                     f'heading that names what this page adds. Change nothing else.')
    return '\n'.join(lines)


def repair(config, data, content, report, *, job, deadline=None):
    """`content` with the reported sections rewritten by one model call, or unchanged.

    Best effort: no time left, a request too large for the plan, or a reply
    that fails validation all leave the document as it was — it is still
    delivered, and the reason is logged. Only the rewritten sections are
    validated and put back: the rest of the document is never validated again,
    because cutting an untouched page to today's limits would change it.
    """
    ids = report.to_repair()
    if not ids:
        return content, None
    order = [s['id'] for s in content['sections']]
    ids = [sid for sid in order if sid in ids][:REPAIR_MAX_SECTIONS]
    selected = data.get('revision', {}).get('selected_section_ids')
    if selected:
        # A selected-page change may only touch the pages it was asked to change.
        ids = [sid for sid in ids if sid in selected]
    if not ids:
        return content, None
    from .pages import batches
    calls = len(batches(len(ids)))
    if deadline is not None and deadline - time.monotonic() < REPAIR_SECONDS_PER_CALL * calls:
        logger.warning('Job %s: quality repair skipped, too little time left (%s)', job.id, report.summary())
        return content, 'no_time'
    fix = copy.deepcopy(data)
    fix.pop('_source_seed', None)
    fix.pop('_written', None)
    fix['content'] = copy.deepcopy(content)
    fix['revision'] = {'request': request_text(report, data['output_locale'], data.get('output_format', 'pdf'), ids),
                       'selected_section_ids': ids, 'base_content': copy.deepcopy(content),
                       'original_prompt': data.get('revision', {}).get('original_prompt') or data.get('prompt', '')}
    fix['_stage'] = 'repair'
    from .domain import validate_content
    from .provider import generate
    from .models import ProviderUsage
    called = False
    try:
        raw, usage = generate(config, fix, job.feature_id, job.id, token_limit=job.quote.policy['generation_bounds']['input_tokens'],
                              deadline=deadline, key_suffix='-repair')
        called = True
        ProviderUsage.objects.create(job=job, provider='openai_repair', model=config['model'],
                                     input_tokens=usage.get('input_tokens', 0), output_tokens=usage.get('output_tokens', 0),
                                     outcome='succeeded')
        returned = {s.get('id'): s for s in raw['sections'] if isinstance(s, dict)}
        # Title, questions and citations are not the repair's to change.
        part = validate_content(job.account, {'title': content.get('title', ''), 'sections': [returned[sid] for sid in ids],
                                              'questions': [], 'citations': []}, data.get('output_format', 'pdf'))
        rewritten = {s['id']: s for s in part['sections']}
        repaired = {**content, 'sections': [rewritten.get(s['id'], s) for s in content['sections']]}
    except Exception as failure:
        if not called:
            ProviderUsage.objects.create(job=job, provider='openai_repair', model=config['model'], outcome='failed')
        logger.warning('Job %s: quality repair failed (%s): %s', job.id, getattr(failure, 'code', type(failure).__name__),
                       report.summary())
        return content, 'failed'
    return repaired, 'repaired'


def finish(config, data, content, *, job, deadline=None, mode='openai'):
    """The checked, corrected and (where needed) repaired content, ready to draw.

    Returns (content, summary) where summary holds codes and counts only. A
    change to selected sections is checked against the whole document but
    corrects only those sections; everything else goes out as it came in.
    """
    locale, fmt = data['output_locale'], data.get('output_format', 'pdf')
    revision = data.get('revision') or {}
    selected = revision.get('selected_section_ids')
    prompt = revision.get('original_prompt') or data.get('prompt', '')
    scope = {'locale': locale, 'fmt': fmt, 'prompt': prompt, 'selected': selected,
             'request': revision.get('request', data.get('prompt', '')) if revision else None}
    report = check(content, **scope, expected=None if selected else len(data['content']['sections']))
    content = _continuing(content, report.ids('continued_heading'))
    content, _ = tidy(content, selected)
    content, fixed = enforce(content, locale, selected)
    outcome, after = None, report
    if mode == 'openai' and report.to_repair():
        content, outcome = repair(config, data, content, report, job=job, deadline=deadline)
        if outcome == 'repaired':
            content, _ = tidy(content, selected)
            content, _ = enforce(content, locale, selected)
            after = check(content, **scope)
            content = _continuing(content, after.ids('continued_heading'))
    summary = {'found': report.summary(), 'transliterated': len(fixed), 'repair': outcome,
               'left': {code: n for code, n in after.summary().items() if code not in ('script', 'continued_heading')}}
    if report.summary() or outcome:
        logger.info('Job %s quality: %s', getattr(job, 'id', None), summary)
    return content, summary


def _continuing(content, ids):
    """`content` with the heading of each continuing page (`ids`) left empty, as the renderer expects."""
    if not ids:
        return content
    return {**content, 'sections': [{**s, 'heading': ''} if s.get('id') in ids else s for s in content['sections']]}


def normalise(content, locale):
    """`content` tidied and in its language's alphabet: the deterministic part of `finish`."""
    content, _ = tidy(content)
    return scripts.enforce(content, locale)[0]
