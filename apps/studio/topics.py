"""What a description says the document must cover, and whether it does.

The model is told the subtopics a description spells out (`required_subtopics`)
so a long deck written in several calls does not lose one; afterwards the
compiled document is checked for each. Only what the customer listed counts —
"including A, B and C", "quyidagilar: A, B, C", a bulleted list — never
subtopics guessed from the subject.
"""
import re

from .language import normalised

ITEM_LINE = re.compile(r'^\s*(?:[-•*–·▪]|\d{1,2}[.)]|[a-zа-я][.)])\s+(.+?)\s*$', re.MULTILINE | re.IGNORECASE)
CUES = re.compile(
    r"(?:\bincluding|\bcovering|\bsuch as|\binclude|\bcover|\btopics?\s*:|\bsections?\s*:|\bsubtopics?\s*:"
    r"|\bshu jumladan|\bjumladan|\bquyidagi\w*(?:\s+[\w']+){0,3}?\s*:|\bo'z ichiga olsin\s*:?|\bmavzular\s*:"
    r"|\bbo'limlar\s*:|включая|в том числе|такие как|следующие\s+\w+\s*:?|разделы\s*:|темы\s*:)\s*",
    re.IGNORECASE)
SPLIT = re.compile(r"\s*(?:[;,]|\band\b|\bva\b|\bhamda\b|(?<![\wЀ-ӿ])и(?![\wЀ-ӿ]))\s*", re.IGNORECASE)
# Counts, formats and languages are instructions about the document, not
# subtopics; so are its form, style and delivery ("modern design", "фото",
# "with speaker notes", "ilmiy uslubda", "a conclusion"). An item with nothing
# left once these are taken out is not sent as a subtopic to cover.
NOT_TOPIC = re.compile(
    r"\b\d+\b|\b(?:in|into|on|ta|tilida|tilda|языке|на)\b|\b(?:slides?|slayd\w*|pages?|bet|sahifa\w*|varaq\w*|слайд\w*|страниц\w*|pdf|pptx|questions?|savol\w*"
    r"|вопрос\w*|english|ingliz\w*|russian|rus\s*til\w*|uzbek|o'zbek\s*til\w*|англ\w*|русск\w*|узбек\w*"
    r"|photo(?:s|graph\w*)?|pictures?|images?|rasm\w*|surat\w*|фото(?!синтез)\w*|картин\w*"
    r"|tables?|jadval\w*|таблиц\w*|designs?|dizayn\w*|дизайн\w*|styles?|uslub\w*|стил\w*|tone|speaker\s+notes"
    r"|conclusions?|xulosa\w*|вывод\w*|заключен\w*|examples?|misol\w*|пример\w*"
    r"|statisti\w*|статистик\w*|bibliography|adabiyotlar\s+ro'yxat\w*|список\s+литератур\w*"
    r"|sources?|manba\w*|источник\w*|languages?|til\w*|язык\w*"
    r"|modern|friendly|scientific|ilmiy|formal|rasmiy)\b",
    re.IGNORECASE)
STOP = set('''the and for with from that this into about their your what which when where how why are was were has have
its can will also than then such other more most some many much each every all any both only very just over under
va bilan uchun haqida ham esa yoki hamda kabi deb bu shu ushbu uning ular qanday nima uchun orqali
и в во на о об с со для по не что как это из к у от при или также который которые является'''.split())


def required(prompt, limit=12):
    """The subtopics a description lists, in order, at most `limit`."""
    body = normalised(prompt)
    found = []
    lines = [match.group(1) for match in ITEM_LINE.finditer(body)]
    if len(lines) >= 2:
        found.extend(lines)
    for match in CUES.finditer(body):
        clause = re.split(r'[.!?\n]', body[match.end():], maxsplit=1)[0]
        parts = [part for part in SPLIT.split(clause) if part]
        if len(parts) >= 2 or (parts and match.group(0).rstrip().endswith(':')):
            found.extend(parts)
    seen, result = set(), []
    for item in found:
        item = item.strip(' \t"\'«»“”()[]:.-–—')
        key = item.lower()
        # "10 slides", "in English": what remains without those words is the subtopic, if any.
        if not 2 <= len(item) <= 80 or ':' in item or key in seen or not stems(NOT_TOPIC.sub(' ', item)):
            continue
        seen.add(key)
        result.append(item)
    return result[:limit]


def stems(text):
    """Word stems that survive suffixes: Uzbek and Russian inflect where English does not."""
    words = re.findall(r"[\wЀ-ӿ']+", normalised(text).lower())
    return {word.replace("'", '')[:5] for word in words if len(word) >= 3 and word not in STOP and not word.isdigit()}


def _alike(a, b):
    """One stem is the other with an ending: a short root keeps all but its last letter
    ('suv' ~ 'suvni', 'вода' ~ 'воды', 'tide' ~ 'tides'), and never fewer than three."""
    size = max(3, min(len(a), len(b)) - 1)
    return len(a) >= size and len(b) >= size and a[:size] == b[:size]


def _index(found):
    index = {}
    for stem in found:
        index.setdefault(stem[:3], []).append(stem)
    return index


def _present(stem, index):
    return any(_alike(stem, other) for other in index.get(stem[:3], ()))


def overlap(these, those):
    """Whether two sets of stems share a word."""
    index = _index(those)
    return any(_present(stem, index) for stem in these)


def missing(subtopics, text):
    """The subtopics that `text` does not mention: fewer than half their stems appear."""
    present = _index(stems(text))
    gaps = []
    for subtopic in subtopics:
        wanted = stems(subtopic)
        if wanted and sum(_present(stem, present) for stem in wanted) * 2 < len(wanted):
            gaps.append(subtopic)
    return gaps
