"""Whether the review screen offers a category's one extra question.

A category may carry `ask`: a question offered as a button on the review
screen, answered at most once with text, files or both, and always skippable
(the customer just taps Create). It is never a refusal, so it is decided here
cheaply and purely, from the message and whether files came with it; whether
it was already answered (`options.details_added`) is the caller's to check.
"""
import re

from ..language import normalised
from .skeleton import stem_found

# A message this short says too little for a few_words question when its entry names no threshold.
FEW_WORDS = 12
WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)*")


def wanted(entry, text, has_files):
    """Whether to offer the entry's question for this message, by its `ask.when`.

    - always: on every new draft of the category;
    - no_digits: the message holds no figure and no file came with it (a
      defence deck with nothing to put on its result slides);
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
        return not has_files and not re.search(r'\d', folded)
    if when == 'few_words':
        return len(WORD.findall(folded)) < ask.get('threshold', FEW_WORDS)
    for field_id in ask['fields']:
        field = entry.field(field_id) or {}
        if field.get('kind') == 'file' and has_files:
            return False
        if any(stem_found(stem, folded) for stems in (field.get('cues') or {}).values() for stem in stems):
            return False
    return True
