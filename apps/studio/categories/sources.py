"""The excerpts a category draft is made from: PDF, Word (.docx and old .doc) and text files.

A draft without a category keeps domain.source_excerpts exactly as it is: PDFs
only, blank pages kept, a scan made into a draft with nothing to quote. A
category draft calls `excerpts` instead, which:

- reads every kind a category takes: a PDF page by page (extraction.extract_pages,
  untouched), a Word or text file in parts of at most 3,000 characters
  (extraction.read_source), so a citation's `page` is a part number there;
- refuses with 'source_unreadable' when the files together hold fewer than
  MIN_LETTERS letters (a scan, a photo saved as PDF, an empty file), and in a
  mix says which files gave no letter at all, dropping them;
- for an entry with `sources.take: head_tail` (a defence deck, a konspekt),
  keeps each file's first and last parts within the character wall instead of
  refusing a long thesis whole, and says it did;
- reuses the stored excerpts while the files are the same ones, so a length
  or language tap on the review does not read every file again.

Every refusal that is about particular files carries their ids
(`{'asset_ids': [...]}`), so the bot can take them out and say why. The text
read is the customer's: it is returned and stored encrypted with the draft,
never logged.
"""
from copy import deepcopy

from apps.core import storage
from apps.core.errors import DomainError
from apps.core.policy import plan_limits
from apps.core.services import owned_assets

# Fewer letters than this in all the files together is no text to work from.
MIN_LETTERS = 40
# The kinds of file a category reads; any other (a picture, a deck) is refused.
KINDS = ('pdf', 'docx', 'doc', 'text')
# The characters one PDF page gives at most, as domain.source_excerpts cuts it.
PDF_PAGE_CHARS = 12000
# The draft option (one of 2.2's server-owned keys) that says a reading kept only
# each file's ends; the files unread are known from the excerpts themselves.
CUT_KEY = 'sources_cut'


def _letters(text):
    return sum(1 for ch in text if ch.isalpha())


def _refused(code, assets, status=400):
    return DomainError(code, status, {'asset_ids': [str(asset.id) for asset in assets]})


def _read(asset):
    """[(page, text)] of one file, or a refusal naming it."""
    kind = asset.metadata.get('kind')
    if kind not in KINDS or (kind == 'pdf' and (asset.mime_type != 'application/pdf' or asset.metadata.get('encrypted'))):
        raise _refused('unsupported_file', [asset])
    from .. import extraction
    try:
        if kind == 'pdf':
            return [(page, text[:PDF_PAGE_CHARS]) for page, text in extraction.extract_pages(storage.local(asset.object_key))]
        return extraction.read_source(storage.local(asset.object_key), kind)
    except DomainError as error:
        # The code says what went wrong; which file it was is what the bot needs to take it out.
        raise DomainError(error.code, error.status, {**error.params, 'asset_ids': [str(asset.id)]}) from None


def _reused(stored, ids, entry, room):
    """The stored excerpts and what was said of them, when the draft holds this entry's reading of these files.

    Only while they still fit: an answer to the review question makes the
    prompt longer, and then the files are read again, so a thesis's ends are
    fitted to the room left (or the draft is refused as it would be anew).
    """
    if not isinstance(stored, dict) or 'excerpts' not in stored:
        return None
    options = stored.get('options') or {}
    if options.get('category') != entry.id or list(stored.get('source_ids') or []) != list(ids):
        return None
    if sum(len(item['text']) for item in stored['excerpts'] or []) > room:
        return None
    excerpts = deepcopy(stored['excerpts'] or [])
    # A file that gave no letter left no excerpt behind (below), so the files
    # unread are the ones the stored excerpts never name.
    named = {item['asset_id'] for item in excerpts}
    return excerpts, {'unread': [str(i) for i in ids if str(i) not in named], 'cut': bool(options.get(CUT_KEY))}


def _head_tail(files, room):
    """Each file's first and last parts, then its next ones from either end in turn, within `room` characters.

    Files take turns, so every file keeps its beginning and its end before any
    keeps a third part. None when even the first and last part of every file
    do not fit together.
    """
    ends = [[0, len(items) - 1, True] for _, items in files]
    kept = [set() for _ in files]
    used, moving = 0, True
    while moving:
        moving = False
        for index, (_, items) in enumerate(files):
            first, last, front = ends[index]
            if first > last:
                continue
            at = first if front else last
            size = len(items[at]['text'])
            if used + size > room:
                # This file's next part does not fit: its middle is left out.
                ends[index][0] = last + 1
                continue
            used += size
            kept[index].add(at)
            ends[index] = [first + 1, last, False] if front else [first, last - 1, True]
            moving = True
    if any(not {0, len(items) - 1} <= kept[index] for index, (_, items) in enumerate(files)):
        return None
    return [item for index, (_, items) in enumerate(files) for at, item in enumerate(items) if at in kept[index]]


def excerpts(account, ids, entry, *, stored=None, room=None):
    """A category draft's excerpts and what the review says of them: (excerpts, {'unread': [asset id], 'cut': bool}).

    `ids` are the draft's `source_ids`; `entry` its category. `stored` is the
    draft as it was saved (an update's `revision_base`): when it holds this
    entry's excerpts of exactly these files they are used again, after the
    files are still looked up so a file gone or not the customer's is refused
    as it always is. `room` is how many characters of excerpts the request has
    space for once the prompt and pasted text are counted (the plan's source
    wall by default).

    An excerpt is today's shape, `{'asset_id', 'page', 'text'}`, and its text
    is exactly what the model is shown, so a quotation can be found again.
    Blank pages are left out. The plan's caps on files and pages are checked
    before anything is read, as in domain.source_excerpts.
    """
    said = {'unread': [], 'cut': False}
    if not ids:
        return [], said
    assets = owned_assets(account, ids)
    caps = plan_limits(account)
    if len(assets) > caps.get('max_ai_source_files', 5) or sum(a.page_count for a in assets) > caps['max_ai_source_pages']:
        raise _refused('generation_limit', assets)
    if room is None:
        from ..domain import limits
        room = limits(account)['source_chars']
    reused = _reused(stored, ids, entry, room)
    if reused is not None:
        return reused
    files, letters = [], 0
    for asset in assets:
        items = [{'asset_id': str(asset.id), 'page': page, 'text': text} for page, text in _read(asset) if text.strip()]
        count = sum(_letters(item['text']) for item in items)
        letters += count
        if count:
            files.append((asset, items))
        else:
            said['unread'].append(str(asset.id))
    if letters < MIN_LETTERS:
        raise _refused('source_unreadable', assets)
    result = [item for _, items in files for item in items]
    if sum(len(item['text']) for item in result) <= room:
        return result, said
    if (entry.raw.get('sources') or {}).get('take') == 'head_tail':
        kept = _head_tail(files, room)
        if kept is not None:
            return kept, {**said, 'cut': True}
    raise _refused('generation_limit', [asset for asset, _ in files])
