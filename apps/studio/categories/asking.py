"""Whether the review screen offers a category's one extra question.

A category may carry `ask`: a question offered as a button on the review
screen, answered at most once with text, files or both, and always skippable
(the customer just taps Create). It is never a refusal, so it is decided here
cheaply and purely, from the message and whether files came with it; whether
it was already answered (`options.details_added`) is the caller's to check.
"""
import re

from .. import pages as paging
from ..language import normalised
from .skeleton import stem_found

# A message this short says too little for a few_words question when its entry names no threshold.
FEW_WORDS = 12
WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)*")
# Numbers that are not results, taken out before no_digits looks for a figure:
# the bot's own prompt asks for the count ("6 ta slayd"), and a title block
# names a course, a group, a school and a year. Left in, any of them hid the
# question, and with it the review line that warns a deck with no figures has
# empty result slides. The count phrases are the ones pages.requested_pages
# reads (NUMBER, LOOSE, AFTER), so a count the quote takes is never a figure.
# The text is NFKC-folded first, so a typed № arrives as "no".
# A group is a code as often as a number ("911-20", "KI-12-20", "гр. 21-05").
# An Uzbek number joined to a word by a hyphen is an ordinal or a label
# ("5-variant", "2-bob", "15-may"), almost never a result, so the whole class
# goes except "-ta"/"-dona", which count things. A slide range ("10-12 slayd")
# is a count and a day with a month name is a date.
# The errors lean one way on purpose: a year-like quantity ("2000 nafar
# respondent") is taken out with the years, and an ordinal that is in fact an
# achievement ("1-o‘rin") with the ordinals, which only offers the skippable
# question once too often, while a label left in would hide it from a deck
# that has no results to show.
_CODE = r"(?:[^\W\d_]+-)?\d+(?:[-/]\d+)*"
_MONTHS = (r"yanvar|fevral|mart(?!a(?:lab)?\b)|aprel|may|iyun|iyul|avgust|sent[ay]?br|okt[ay]?br|noyabr|dekabr"
           r"|январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр"
           r"|january|february|march|april|june|july|august|september|october|november|december")
# The labels go first: the count patterns would take "12 slayd" out of
# "10-12 slayd" and leave the 10 behind as a figure.
NOT_FIGURES = (
    re.compile(r"(?<!\w)(?:guruh|группа|гр\.?|group|no\.?)\s*[:№]?\s*" + _CODE
               + r"|(?<![\w-])" + _CODE + r"\s*-?\s*(?:guruh|групп|group)\w*"
               r"|(?<![\d.,])\d+\s*[-–]\s*\d+\s*(?:ta\s+)?(?:slayd|слайд|slide)\w*"
               r"|(?<![\d.,])\d{1,2}\s*-?\s*(?:" + _MONTHS + r")\w*"
               r"|(?:" + _MONTHS + r")\s+\d{1,2}(?:st|nd|rd|th)?(?![\d.,])"
               r"|\d+\s*-?\s*(?:kurs|sinf|yil|bosqich|semestr|maktab)\w*"
               r"|\d+ ?- ?(?!(?:ta|dona)\b)[^\W\d_]+"
               r"|\d+\s*(?:-?\s*(?:й|я|го|м|ой))?\s*(?:курс|класс|семестр|школ)\w*"
               r"|(?:grade|year|class|form|semester)\s+\d+|\d+(?:st|nd|rd|th)[\s-]+(?:year|grade)"
               r"|(?<![\d.,])\d{1,2}[./]\d{1,2}[./]\d{2,4}(?![\d.,])"
               r"|(?<![\d.,])(?:19|20)\d{2}(?![\d.,%])(?!\s*(?:-\s*)?(?:ta|dona)\b)"),
    paging.NUMBER, paging.LOOSE, paging.AFTER,
)


def figures(text):
    """Whether folded `text` holds a figure once counts, ordinals, labels and years are taken out."""
    for pattern in NOT_FIGURES:
        text = pattern.sub(' ', text)
    return re.search(r'\d', text) is not None


def wanted(entry, text, has_files):
    """Whether to offer the entry's question for this message, by its `ask.when`.

    - always: on every new draft of the category;
    - no_digits: the message holds no figure and no file came with it (a
      defence deck with nothing to put on its result slides); a slide count,
      a course, group or school number or code, an ordinal, a date and a
      year are not figures (`figures`);
    - few_words: the message has fewer words than `ask.threshold`;
    - cues_missing: none of the asked fields is found in the message, by its
      cue stems, or for a file field by an attached file.
    An entry without a question never offers one.
    """
    ask = entry.raw.get('ask')
    if not ask:
        return False
    folded = normalised(text or '').casefold()
    when = ask['when']
    if when == 'always':
        return True
    if when == 'no_digits':
        return not has_files and not figures(folded)
    if when == 'few_words':
        return len(WORD.findall(folded)) < ask.get('threshold', FEW_WORDS)
    for field_id in ask['fields']:
        field = entry.field(field_id) or {}
        if field.get('kind') == 'file' and has_files:
            return False
        if any(stem_found(stem, folded) for stems in (field.get('cues') or {}).values() for stem in stems):
            return False
    return True
