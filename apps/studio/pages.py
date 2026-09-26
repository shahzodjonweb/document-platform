"""How many pages a description asks for, and how much prose fills them.

The numbers here were measured against the renderers rather than estimated, and
they are in characters rather than words on purpose: a page fills by character,
and word length varies enough between English, Uzbek and Russian that a word
target exact in one is a page out in another. At 3000 characters a section
occupies exactly one A4 page for every one of the three, from one section to
eight; a slide holds roughly 650.

tests/test_page_fill.py renders for real and will fail if these drift.
"""
import re
import unicodedata

from apps.core.policy import plan_limits

# Measured across short English, long English and Russian prose: 2700-3000
# characters is one page in all three, 3200 spills the long-word cases.
CHARS_PER_PAGE = 3000
# A slide holds eleven lines; this is about what fills them.
CHARS_PER_SLIDE = 650
DEFAULT_PAGES = 5

# A page of prose costs roughly this much of the response, taking the worst of
# the three locales' tokenizers and leaving room for the heading and the JSON
# around it. The ceiling is what we ask the provider for at most.
PAGE_TOKENS = 1100
RESPONSE_BASE_TOKENS = 800
RESPONSE_CEILING = 16000
# Beyond this, one response cannot hold full pages however generous the plan is.
MAX_PAGES = (RESPONSE_CEILING - RESPONSE_BASE_TOKENS) // PAGE_TOKENS

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
    """The most pages this account can be given in one document."""
    caps = plan_limits(account)
    plan_cap = caps['max_generated_slides' if output_format == 'pptx' else 'max_generated_pdf_pages']
    return max(1, min(plan_cap, MAX_PAGES))


def resolve(account, text, output_format):
    """Pages to produce and pages asked for, so a clamp can be shown, not hidden."""
    asked = requested_pages(text)
    return min(asked or DEFAULT_PAGES, ceiling(account, output_format)), asked


def chars_per_page(output_format):
    return CHARS_PER_SLIDE if output_format == 'pptx' else CHARS_PER_PAGE


def response_tokens(pages):
    return min(RESPONSE_CEILING, RESPONSE_BASE_TOKENS + pages * PAGE_TOKENS)
