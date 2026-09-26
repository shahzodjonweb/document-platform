"""How many pages a description asks for, and how much prose fills them.

The numbers here were measured against the renderers rather than estimated, and
they are in characters rather than words on purpose: a page fills by character,
and word length varies enough between English, Uzbek and Russian that a word
target exact in one is a page out in another. A page holds about 3000 characters
in all three, and a slide about 650 — but what the model is asked for is less
than that, because sections overshoot together and so spill together.

tests/test_page_fill.py renders for real and will fail if these drift.
"""
import re
import unicodedata

from apps.core.policy import plan_limits

# What one page HOLDS, measured across short English, long English and Russian
# prose: 2700-3000 characters is one page in all three.
CHARS_PER_PAGE = 3000
# A slide holds eleven lines; this is about what fills them.
CHARS_PER_SLIDE = 650
DEFAULT_PAGES = 5

# What we ASK the model for is deliberately less than the page holds. A model
# told "about 3000 characters" routinely lands 15-20% over, and because every
# section gets the same instruction they overshoot together: at 3500 characters
# all five sections of a five-page document spill at once and it renders as ten
# pages (tests/test_page_fill.py measures this). Aiming at 85% of capacity keeps
# the whole overshoot band on the page, so N sections really are N pages.
FILL_RATIO = 0.85
# Characters are the right unit for measuring a page and the wrong one for
# asking a model to write: it cannot count them, and told "about 2550
# characters" it writes whatever it considers a full page — twice the target,
# in practice. Words it can approximate, sentences and paragraphs it can count,
# so the guidance is given in those and derived from here. Averaged over the
# three locales, a word and its space run about this wide.
CHARS_PER_WORD = 6.5

# A page of prose costs roughly this much of the response, taking the worst of
# the three locales' tokenizers and leaving room for the heading and the JSON
# around it.
PAGE_TOKENS = 1100
RESPONSE_BASE_TOKENS = 800
# One response is asked for at most this much. It bounds a single call, not the
# document: longer documents are written in several calls of PAGES_PER_CALL
# sections each, so the page ceiling comes from the plan rather than from how
# much a model can say in one breath.
RESPONSE_CEILING = 16000
# Sections per call. Five pages short of what the ceiling would allow, because a
# response that runs out of room mid-JSON is unparseable and loses the whole call
# — the margin is worth more than the round trip it saves.
PAGES_PER_CALL = max(1, (RESPONSE_CEILING - RESPONSE_BASE_TOKENS) // PAGE_TOKENS - 5)

WORDS = {
    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7,
    'eight': 8, 'nine': 9, 'ten': 10, 'eleven': 11, 'twelve': 12, 'fifteen': 15,
    'twenty': 20,
    'bir': 1, 'ikki': 2, 'uch': 3, "to'rt": 4, 'besh': 5, 'olti': 6, 'yetti': 7,
    'sakkiz': 8, "to'qqiz": 9, "o'n": 10,
    'один': 1, 'одна': 1, 'два': 2, 'две': 2, 'три': 3, 'четыре': 4, 'пять': 5,
    'шесть': 6, 'семь': 7, 'восемь': 8, 'девять': 9, 'десять': 10,
}
UNITS = (r'(?:pages?|slides?|sahifa\w*|bet(?:lik|lar|li)?|varaq\w*|slayd\w*'
         r'|страниц\w*|стр|слайд\w*)\b')
# Uzbek counts with a classifier between the number and the noun: "6 ta slayd".
COUNTED = r'\s*[-–]?\s*(?:ta|dona)?\s*'
NUMBER = re.compile(r'(\d{1,3})' + COUNTED + UNITS, re.IGNORECASE)
SPELLED = re.compile(r"([\w'’]+)" + COUNTED + UNITS, re.IGNORECASE | re.UNICODE)


def _normalised(text):
    """Uzbek is written with several apostrophes; treat them as one."""
    folded = unicodedata.normalize('NFKC', text or '')
    return folded.replace('‘', "'").replace('’', "'").replace('ʻ', "'").replace('ʼ', "'")


def requested_pages(text):
    """The page count named in a description, or None when it names none."""
    body = _normalised(text)
    match = NUMBER.search(body)
    if match:
        count = int(match.group(1))
        return count if count > 0 else None
    for candidate in SPELLED.finditer(body):
        count = WORDS.get(candidate.group(1).lower())
        if count:
            return count
    return None


QUESTION_UNITS = r'(?:questions?|savol\w*|вопрос\w*|тест\w*)\b'
QUESTIONS = re.compile(r'(\d{1,3})' + COUNTED + QUESTION_UNITS, re.IGNORECASE)
SPELLED_QUESTIONS = re.compile(r"([\w'’]+)" + COUNTED + QUESTION_UNITS, re.IGNORECASE | re.UNICODE)


def requested_questions(text):
    """Questions are priced, so they are only included when they are asked for."""
    body = _normalised(text)
    match = QUESTIONS.search(body)
    if match:
        return int(match.group(1))
    for candidate in SPELLED_QUESTIONS.finditer(body):
        count = WORDS.get(candidate.group(1).lower())
        if count:
            return count
    return 0


def ceiling(account, output_format):
    """The most pages this account can be given in one document.

    The plan is the only limit. Nothing about how the document is produced
    reduces it: a count the plan allows is a count we have to deliver.
    """
    caps = plan_limits(account)
    plan_cap = caps['max_generated_slides' if output_format == 'pptx' else 'max_generated_pdf_pages']
    return max(1, plan_cap)


def resolve(account, text, output_format):
    """Pages to produce and pages asked for, so a clamp can be shown, not hidden."""
    asked = requested_pages(text)
    return min(asked or DEFAULT_PAGES, ceiling(account, output_format)), asked


def chars_per_page(output_format):
    """What one page of this output format holds."""
    return CHARS_PER_SLIDE if output_format == 'pptx' else CHARS_PER_PAGE


def max_section_chars(output_format):
    """A hard stop on one section, far above anything a brief asks for.

    Real output never reaches it; a model that runs away is trimmed here rather
    than costing the customer the whole document.
    """
    return chars_per_page(output_format) * 4


def target_chars(output_format):
    """What to ask the model for, so its overshoot still fits the page."""
    return int(chars_per_page(output_format) * FILL_RATIO)


def target_words(output_format):
    """The same target in the unit the model is actually asked in."""
    return max(20, round(target_chars(output_format) / CHARS_PER_WORD))


def response_tokens(pages):
    return min(RESPONSE_CEILING, RESPONSE_BASE_TOKENS + pages * PAGE_TOKENS)


def batches(count, per_call=PAGES_PER_CALL):
    """Section index ranges to ask for, one per provider call.

    Splitting is what lets a plan offer more pages than one response can hold,
    and it keeps every call's `max_output_tokens` inside RESPONSE_CEILING.
    """
    return [(start, min(start + per_call, count)) for start in range(0, max(1, count), per_call)]
