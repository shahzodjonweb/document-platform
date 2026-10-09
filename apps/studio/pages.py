"""How many pages a description asks for, and how much prose fills them.

The numbers here were measured against the renderers rather than estimated, and
they are in characters rather than words on purpose: a page fills by character,
and word length varies enough between English, Uzbek and Russian that a word
target exact in one is a page out in another. A page holds about 3000 characters
in all three, and a slide of bullets about 500 — but what the model is asked for
is less than that, because sections overshoot together and so spill together.

tests/test_page_fill.py renders for real and will fail if these drift.
"""
import re
import unicodedata

from apps.core.policy import plan_limits

# What one page HOLDS, measured across short English, long English and Russian
# prose: 2700-3000 characters is one page in all three.
CHARS_PER_PAGE = 3000
# A slide holds a headline and four to six sentence-long bullets. This is about
# what fills them. It was 500 when bullets were fourteen-word fragments, and
# customers found the decks too thin to present from.
CHARS_PER_SLIDE = 850
DEFAULT_PAGES = 5
# What the deck setup screen (the bot's Mini App) starts at. What it sends is
# an explicit count, so it beats the description's like the review stepper.
SETUP_SLIDES = 7

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
# around it. A document's page is asked for at a page and a quarter (see
# FLOW_FILL_RATIO), so this covers that.
PAGE_TOKENS = 1500
RESPONSE_BASE_TOKENS = 800
# One response is asked for at most this much. It bounds a single call, not the
# document: longer documents are written in several calls of PAGES_PER_CALL
# sections each, so the page ceiling comes from the plan rather than from how
# much a model can say in one breath.
RESPONSE_CEILING = 24000
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
UNIT_WORDS = (r"pages?|slides?|sahifa\w*|bet(?:lik|lar|li|dan)?|var[ao]q\w*|slayd\w*"
              r"|страниц\w*|стр|слайд\w*|лист(?:а|ов)?")
UNITS = r'(?:' + UNIT_WORDS + r')\b'
# Uzbek counts with a classifier between the number and the noun: "6 ta slayd".
COUNTED = r'\s*[-–]?\s*(?:ta|dona)?\s*'
NUMBER = re.compile(r'(\d{1,3})(' + COUNTED + r')(' + UNIT_WORDS + r')\b', re.IGNORECASE)
SPELLED = re.compile(r"([\w'’]+)" + COUNTED + UNITS, re.IGNORECASE | re.UNICODE)
# Uzbek numbers a page with a hyphen: "1-bet" is page one, "3-slayd" the third
# slide. A pasted essay or slide plan is full of them, and each one read as a
# count turned a whole essay into a one-slide deck. "10-betlik" and "12-page"
# are still counts.
ORDINAL_NOUN = re.compile(r"(?:bet|sahifa|slayd|var[ao]q)(?:da|ga|ning|dan|ni|si|i)?", re.IGNORECASE)
# "har 1ta slaydga rasm", "har bir slaydda": something on every slide, not a count.
EACH = re.compile(r"(?:\bhar|\beach|\bevery|\bper|кажд\w*)\s+(?:bir\s+)?$", re.IGNORECASE)
# Nouns that a number counts instead of pages: "9 sinf", "5 ta savol", "4 ta rasm".
COUNTED_NOUNS = (r"(?:savol|rasm|fikr|reja|misol|test|ball|bo'lim|qism|sinf|kurs|yil|asr|guruh|bob|mavzu"
                 r"|daqiqa|minut|soat|kun|вопрос|класс|курс|минут|картин|фото)\w*")
LETTERS = r"(?:[^\W\d_]|')"
# One word between the count and the noun: "10 ta chiroyli slayd", "14tashlab slayd".
LOOSE = re.compile(r"(\d{1,3})(?:\s*[-–]?\s*ta)?(" + LETTERS + r"*)\s+(?:(" + LETTERS + r"+)\s+)?" + UNITS,
                   re.IGNORECASE | re.UNICODE)
# The count after the noun: "Sahifalar soni 20 ta", "количество слайдов: 12".
AFTER = re.compile(r"(?:sahifa|slayd|bet|var[ao]q|page|slide)\w*\s+(?:soni|sonini|miqdori)\s*[:\-–]?\s*(\d{1,3})"
                   r"|количеств\w*\s+(?:слайд|страниц|лист)\w*\s*[:\-–]?\s*(\d{1,3})", re.IGNORECASE)
# No noun at all, only when nothing else names a count: "15 ta bo'lsin".
NOUNLESS = re.compile(r"(\d{1,3})\s*[-–]?\s*ta(?:dan)?\s+(?:bo'lsin|bolsin|bulsin|bo'lishi|kerak|qil\w*|tayyorla\w*)\b",
                      re.IGNORECASE)


def _normalised(text):
    """Uzbek is written with several apostrophes, and some keyboards type o‘ as ó; treat them as one."""
    folded = unicodedata.normalize('NFKC', text or '')
    for mark in ('‘', '’', 'ʻ', 'ʼ', '`', '´'):
        folded = folded.replace(mark, "'")
    folded = re.sub('[óòōŏ]', "o'", folded)
    folded = re.sub('[ÓÒŌŎ]', "O'", folded)
    return folded.replace('ğ', "g'").replace('Ğ', "G'")


def _each(body, start):
    return bool(EACH.search(body[max(0, start - 16):start]))


def requested_pages(text):
    """The page count named in a description, or None when it names none."""
    body = _normalised(text)
    ordinals = set()
    for match in NUMBER.finditer(body):
        count, between, unit = int(match.group(1)), match.group(2), match.group(3)
        if '-' in between.replace('–', '-') and 'ta' not in between.lower() and ORDINAL_NOUN.fullmatch(unit):
            ordinals.add(count)
        elif count > 0 and not _each(body, match.start()):
            return count
    after = AFTER.search(body)
    if after:
        count = int(after.group(1) or after.group(2))
        if count > 0:
            return count
    # A pasted plan numbers its slides "1-slayd … 9-slayd": the last one is the count.
    if len(ordinals) > 1:
        return max(ordinals)
    for match in LOOSE.finditer(body):
        glued, filler = match.group(2), match.group(3) or ''
        if (int(match.group(1)) > 0 and not _each(body, match.start())
                and not re.fullmatch(COUNTED_NOUNS, glued, re.IGNORECASE)
                and not re.fullmatch(COUNTED_NOUNS, filler, re.IGNORECASE)):
            return int(match.group(1))
    for candidate in SPELLED.finditer(body):
        count = WORDS.get(candidate.group(1).lower())
        if count and not _each(body, candidate.start()):
            return count
    for match in NOUNLESS.finditer(body):
        if int(match.group(1)) > 0 and not _each(body, match.start()):
            return int(match.group(1))
    return None


QUESTION_UNITS = r'(?:questions?|savol\w*|вопрос\w*|тест\w*)\b'
QUESTIONS = re.compile(r'(\d{1,3})' + COUNTED + QUESTION_UNITS, re.IGNORECASE)
SPELLED_QUESTIONS = re.compile(r"([\w'’]+)" + COUNTED + QUESTION_UNITS, re.IGNORECASE | re.UNICODE)


# A deck's questions share slides, this many to a slide.
QUESTIONS_PER_SLIDE = 5


def question_slides(count):
    """Slides a deck's questions take at the end."""
    return -(-max(0, count) // QUESTIONS_PER_SLIDE)


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


# A document flows from one section into the next and is then held to its page
# count as a whole (rendering.fit_document): a section that runs long is set a
# little tighter rather than spilling. So a document is asked for more than a
# page per section. Measured in production, the model writes about two thirds of
# what it is asked for: seven sections asked at 0.95 of a page came back as five
# pages. What it overshoots, the renderer absorbs; what it still falls short of,
# filling.top_up writes further. A deck's slides still each hold their own.
FLOW_FILL_RATIO = 1.25


def target_chars(output_format):
    """What to ask the model for, so its overshoot still fits the page."""
    ratio = FILL_RATIO if output_format == 'pptx' else FLOW_FILL_RATIO
    return int(chars_per_page(output_format) * ratio)


def target_words(output_format):
    """The same target in the unit the model is actually asked in."""
    return max(20, round(target_chars(output_format) / CHARS_PER_WORD))


def response_tokens(pages):
    return min(RESPONSE_CEILING, RESPONSE_BASE_TOKENS + pages * PAGE_TOKENS)


# A reasoning model spends part of its output budget thinking before it writes.
# The last call of a ten-slide deck covers slides 9-10 and was given 3000
# tokens; the thinking used them up, the answer was cut off, and the whole deck
# failed. No writing call is given less than this.
MIN_CALL_TOKENS = 6000
# The questions are written in the last call, so its budget grows with them.
QUESTION_TOKENS = 200


def call_tokens(pages, questions=0):
    """What one writing call may spend: its pages, its questions, and room to think."""
    return min(RESPONSE_CEILING, max(MIN_CALL_TOKENS, response_tokens(pages)) + QUESTION_TOKENS * questions)


def batches(count, per_call=PAGES_PER_CALL):
    """Section index ranges to ask for, one per provider call.

    Splitting is what lets a plan offer more pages than one response can hold,
    and it keeps every call's `max_output_tokens` inside RESPONSE_CEILING.
    """
    return [(start, min(start + per_call, count)) for start in range(0, max(1, count), per_call)]


# What a deck should look like, read out of the description like everything
# else — unless a design was picked on the review screen, which wins.
THEMES = ('light', 'dark', 'bold')
THEME_WORDS = (
    ('dark', r'dark|night\s*mode|qorong\'?i|tungi|т[ёе]мн\w*|ночн\w*'),
    ('bold', r'bold|vivid|striking|punchy|high[-\s]?contrast|yorqin|jasur|ярк\w*|смел\w*|контрастн\w*'),
    ('light', r"light\s*(?:theme|background)|minimal|oq\s*fon|och\s*rang\w*|och\s*tus\w*|pastel\w*|пастел\w*"
              r"|ko'zni\s*charchatmaydigan\w*|yumshoq\s*rang\w*|soft\s*colou?rs?|св[ея]тл\w*|минималист\w*"),
)
# A colour named in the brief becomes the accent, and the palette derives the
# rest from it. Account branding still wins: a brand colour is not a preference.
COLOURS = (
    ('#16305C', r'navy|dark\s*blue|to\'?q\s*ko\'?k|тёмно-син\w*|нав\w*'),
    # Sky blue: "och havorang", "moviy", "zangori"; "savorang" is how it is often typed.
    ('#2B7BB9', r"sky\s*blue|light\s*blue|och\s*ko'?k|havo\s*rang\w*|havorang\w*|savorang\w*|osmon\s*rang\w*"
                r"|moviy\w*|zangori\w*|голуб\w*|небесн\w*"),
    ('#1F4E9C', r'blue|ko\'?k|син\w*'),
    ('#146B6B', r'teal|turquoise|feruza|бирюз\w*'),
    ('#1E6B45', r'green|emerald|yashil|зел[ёе]н\w*|изумруд\w*'),
    ('#6E1230', r'burgundy|maroon|wine|bordo|бордов\w*'),
    ('#9B1B1B', r'red|crimson|qizil|красн\w*|алы[йе]'),
    ('#B2541A', r'orange|amber|to\'?q\s*sariq|оранжев\w*|янтарн\w*'),
    ('#8A6A10', r'gold|mustard|oltin|sariq|золот\w*|горчичн\w*|ж[ёе]лт\w*'),
    ('#4B2E83', r'purple|violet|indigo|binafsha|фиолетов\w*|сирен\w*|индиго'),
    ('#A3246B', r'pink|magenta|pushti|розов\w*|пурпурн\w*'),
    ('#2B2F33', r'charcoal|graphite|slate|grey|gray|kulrang|сер\w*|графит\w*'),
    ('#6B4423', r"brown|jigar\s*rang\w*|qo'ng'ir\w*|коричнев\w*"),
    ('#14171A', r'black|qora|ч[ёе]рн\w*'),
)


def requested_theme(text):
    """The deck style a description asks for, or None when it asks for none."""
    body = _normalised(text).lower()
    for name, pattern in THEME_WORDS:
        if re.search(r'\b(?:' + pattern + r')', body, re.IGNORECASE | re.UNICODE):
            return name
    return None


def requested_colours(text):
    """The colours named in the description, as hex, in the order they are named."""
    body = _normalised(text).lower()
    found = []
    for value, pattern in COLOURS:
        for match in re.finditer(r'\b(?:' + pattern + r')', body, re.IGNORECASE | re.UNICODE):
            found.append((match.start(), -match.end(), value))
    taken, ordered = [], []
    # "to'q ko'k" is navy, not navy and blue: a name inside a longer one is part of it.
    for start, end, value in sorted(found):
        if any(first <= start < last for first, last in taken):
            continue
        taken.append((start, -end))
        if value not in ordered:
            ordered.append(value)
    return ordered


def requested_accent(text):
    """The first colour named in the description, as a hex accent, or None."""
    named = requested_colours(text)
    return named[0] if named else None


# The language a description asks for. "ingliz tilida" counts when it is how
# the request ends or comes before what to do ("ingliz tilida tayyorla"), not
# when it names the subject ("Xitoy tilida omonimlar", "rus tili fani").
LANGUAGE_WORDS = {
    'en': r"ingi?liz|english|англи\w*",
    'ru': r"rus|russian|русск\w*",
    'uz': r"o'zbek|uzbek|узбек\w*",
}
DOING = (r"(?:tayyorla\w*|yoz\w*|bo'lsin|bolsin|bo'lishi|qil\w*|kerak|chiqsin|chiqar\w*|ber\w*|ishla\w*"
         r"|сделай\w*|напиши\w*|подготов\w*|нужн\w*)")


def _language_patterns(words):
    ends = r"(?=\s*(?:[.,!;:)\n]|$|(?:\S+\s+)?" + DOING + r"))"
    return [
        re.compile(r"\b(?:" + words + r")\s*(?:til(?:i|)da|tilda|language\w*|tilida)\b" + ends, re.IGNORECASE),
        re.compile(r"\b(?:" + words + r")cha\b" + ends, re.IGNORECASE),
        re.compile(r"\bin\s+(?:" + words + r")\b", re.IGNORECASE),
        re.compile(r"(?:на|по-)\s*(?:" + words + r")", re.IGNORECASE),
    ]


LANGUAGE_PATTERNS = {code: _language_patterns(words) for code, words in LANGUAGE_WORDS.items()}
CYRILLIC = re.compile(r'[Ѐ-ӿ]')
LATIN = re.compile(r'[A-Za-z]')
UZBEK_CYRILLIC = re.compile(r'[ЎўҚқҒғҲҳ]')
RUSSIAN_WORDS = re.compile(r'(?<![\wЀ-ӿ])(?:и|в|на|о|об|с|для|по|не|что|как|это|из|к|у|от|при|или)'
                           r'(?![\wЀ-ӿ])', re.IGNORECASE)
UZBEK_WORDS = re.compile(r'(?<![\wЀ-ӿ])(?:ва|учун|билан|ҳақида|хақида|ҳам|хам|бу|мен|сен|керак|бўлсин)'
                         r'(?![\wЀ-ӿ])|[Ѐ-ӿ]+(?:лари|ларни|нинг|даги|лик)\b', re.IGNORECASE)


def _cyrillic_share(text):
    cyrillic, latin = len(CYRILLIC.findall(text)), len(LATIN.findall(text))
    return cyrillic / (cyrillic + latin) if cyrillic + latin else 0.0


def requested_locale(text, *, explicit_only=False):
    """The language a description asks the document to be written in, or None.

    A language named as the output wins. Failing that, a description written
    in Russian is answered in Russian (not for a change request, which may be
    written in any language about a document that stays in its own).
    """
    body = _normalised(text)
    found = []
    for code, patterns in LANGUAGE_PATTERNS.items():
        for pattern in patterns:
            match = pattern.search(body)
            if match:
                found.append((match.start(), code))
                break
    if found:
        return min(found)[1]
    if explicit_only:
        return None
    if (_cyrillic_share(body) >= 0.6 and not UZBEK_CYRILLIC.search(body)
            and len(RUSSIAN_WORDS.findall(body)) >= 2 and not UZBEK_WORDS.search(body)):
        return 'ru'
    return None


def requested_script(text):
    """'cyrl' for a description written in Uzbek Cyrillic, else 'latn'."""
    body = _normalised(text)
    return 'cyrl' if _cyrillic_share(body) >= 0.5 and requested_locale(body) != 'ru' else 'latn'


PICTURES = re.compile(r"(\d{1,2})\s*(?:[-–]?\s*ta)?\s*(?:rasm|surat|picture|image|photo|картин|фото|изображ)\w*",
                      re.IGNORECASE)


def requested_images(text):
    """How many pictures a description asks for by number ("4 ta rasm"), or None."""
    match = PICTURES.search(_normalised(text))
    return int(match.group(1)) if match and int(match.group(1)) > 0 else None


# Which service a description is asking for, when it names one: a request
# for slides sent to the PDF service came back as a seven-page PDF.
SLIDE_WORDS = re.compile(r"slayd\w*|slide\w*|taqdimot\w*|prezentats\w*|презентац\w*|слайд\w*|pptx|power\s*point",
                         re.IGNORECASE)
DOCUMENT_WORDS = re.compile(r"\bpdf\b|referat\w*|hujjat\w*|реферат\w*|документ\w*|\bdocument\w*", re.IGNORECASE)


def names_slides(text):
    return bool(SLIDE_WORDS.search(_normalised(text)))


def names_document(text):
    return bool(DOCUMENT_WORDS.search(_normalised(text)))
