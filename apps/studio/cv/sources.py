"""Where a CV's facts come from: one message, the customer's LinkedIn profile, or their old CV.

The customer chooses first (`options.cv_source`). 'text' is the one message a
CV has always been made from. 'linkedin' is their LinkedIn profile, which our
server cannot open: LinkedIn needs a sign-in and forbids reading its pages by
program, so it is the profile saved with LinkedIn's own "Save to PDF", or
screenshots of it. 'file' is an old CV: a PDF, a Word file, photos or a scan.
In those two the file holds the facts and what the customer writes is notes
on top of it: the job they want now, what to change, what to add. A photo
sent there is a page to read, never the portrait.

Each file is read once, as it arrives: it is queued for the reader when it
is uploaded (cv/reads.py), and `runreader` reads it in the bounded child
(extraction.read_cv), never a request or the bot. A draft is made from what
the reader kept, and what its files say is kept with the draft as its
excerpts; while a file is still waiting for the reader, the draft is refused
with `cv_reading`, which says how many reads are ahead, and the customer is
told to wait, not to try again. An update that keeps the files keeps what
was read, one that adds a file takes what the reader made of that file, and
a change to the CV is made from the excerpts it was made from, after the
files themselves are gone (they are kept 24 hours). What could not be read
(pages past the OCR share, a file the reader failed on) is kept with the
draft as `cv_unread` and said on its review, never left out unsaid.
"""
import re

from apps.core.errors import DomainError

TEXT, LINKEDIN, FILE = 'text', 'linkedin', 'file'
MODES = (TEXT, LINKEDIN, FILE)
# What each mode takes. A LinkedIn profile is its own PDF or screenshots of it, never a Word file.
KINDS = {LINKEDIN: ('pdf', 'image'), FILE: ('pdf', 'docx', 'image')}
MIME = {'application/pdf': 'pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
        'image/jpeg': 'image', 'image/png': 'image'}
# Ten files: an album of screenshots is at most ten. Pages are all the files' together.
MAX_FILES = 10
MAX_PAGES = 30
# Pages read by OCR for one draft, all its files together (shared), and so
# for one file at most; and how long the reader may take over one file.
MAX_OCR_PAGES = 10
READ_SECONDS = 60
# Fewer words than this in all the files is a file with nothing to read in it.
MIN_WORDS = 8
# A LinkedIn profile's address: linkedin.com/in/…, an older /pub/ one, or a lnkd.in short link.
LINKEDIN_LINK = re.compile(r"(?:https?://)?(?:[\w\-]+\.)?(?:linkedin\.com/(?:in|pub|profile)/|lnkd\.in/)[^\s<>]*",
                           re.IGNORECASE)


def mode(options):
    """The way the CV is made, as `options` names it: 'text' when it names none."""
    source = (options or {}).get('cv_source', TEXT)
    if source not in MODES:
        raise DomainError('invalid_parameters')
    return source


def max_files(account):
    """How many files a CV may be made from: ten, or fewer when the plan's source files are fewer."""
    from apps.core.policy import plan_limits
    return min(MAX_FILES, int(plan_limits(account).get('max_ai_source_files', MAX_FILES) or MAX_FILES))


def max_pages(account):
    """How many pages all of a CV's files may have: thirty, or fewer when the plan's source pages are fewer."""
    from apps.core.policy import plan_limits
    return min(MAX_PAGES, int(plan_limits(account).get('max_ai_source_pages', MAX_PAGES) or MAX_PAGES))


# The words people ask with, greet with and point at their profile with, in
# English, Uzbek and Russian. None of them is a fact about the person. The web
# app stops a link-only description with the same set (document-web
# app/composables/useCvSources.ts ASKING) and never with a word more: a word
# only the web took for asking would stop a description this side makes a CV of.
ASKING = frozenset(' '.join((
    'hello hi here is my the a an at from for me it please make create professional good cv resume profile link page',
    'thank thanks you very much this',
    'assalomu alaykum salom mana mening shu shundan menga yaxshi rezyume profil profilim havola qilib bering iltimos',
    'tayyorlab rahmat',
    'здравствуйте привет вот ссылка на мой моя мне профиль в из него по моему сделайте сделать составьте пожалуйста',
    'резюме спасибо',
)).split())
LETTERS = re.compile(r"[^\W\d_]+")


def linkedin_link_only(text):
    """Whether a description is a LinkedIn profile's link and no fact about the person.

    A bare link, or one in a request ("Здравствуйте, вот ссылка на мой
    профиль, сделайте резюме: …", "Please make my CV from my profile at …").
    It cannot be opened, so the customer is told how to save the profile as a
    PDF instead (`cv_linkedin_link`). Any other word, an email, a phone number
    or a year is a fact, however short the description ("Ali Valiyev, SMM
    manager. linkedin.com/in/…"), and the CV is made from it. A name alone is
    no CV: it is taken out before the words are read, so a request that gives
    only the name and the link is still told how to save the profile.
    """
    text = str(text or '')
    if not LINKEDIN_LINK.search(text):
        return False
    from .content import EMAIL, PHONE, YEAR, name_in
    rest = LINKEDIN_LINK.sub(' ', text)
    name = name_in(rest)
    if name:
        rest = rest.replace(name, ' ', 1)
    if EMAIL.search(rest) or PHONE.search(rest) or YEAR.search(rest):
        return False
    words = [word.lower() for word in LETTERS.findall(rest)]
    return all(word == 'linkedin' or word in ASKING for word in words)


def checked(account, ids, source):
    """The files of a CV made from files, checked for its mode before any is read: (assets, kinds).

    Refused: `generation_limit` for more files or pages than one CV is made
    from, `cv_file_kind` for a file the mode does not read, `cv_file_unreadable`
    for a protected PDF.
    """
    if len(ids) > max_files(account):
        raise DomainError('generation_limit')
    from apps.core.services import owned_assets
    assets = owned_assets(account, ids)
    kinds = [kind_of(asset) for asset in assets]
    if any(kind not in KINDS[source] for kind in kinds):
        raise DomainError('cv_file_kind')
    if any(asset.metadata.get('encrypted') for asset in assets):
        raise DomainError('cv_file_unreadable')
    if sum(asset.page_count for asset in assets) > max_pages(account):
        raise DomainError('generation_limit')
    return assets, kinds


def prepare(account, prompt, ids, options, previous=None):
    """The files of a new CV checked for its mode, and what the reader made of them: (ids, excerpts, unread).

    'text' takes none. 'linkedin' and 'file' take one to ten of the kinds
    their mode reads (KINDS). `previous` is the draft being updated: its
    excerpts are kept when its files are, and a file it read whole needs no
    read beside a new one. `unread` says what could not be read (read).
    Refused: `cv_file_required` with no file, `cv_linkedin_link` when the
    description is only a LinkedIn link, the refusals of checked(),
    `cv_reading` while a file is still being read, and `cv_file_unreadable`
    for files with no text in them.
    """
    source = mode(options)
    if not isinstance(ids, list):
        raise DomainError('invalid_parameters')
    if source == TEXT:
        if ids:
            raise DomainError('invalid_parameters')
        if linkedin_link_only(prompt):
            raise DomainError('cv_linkedin_link')
        return ids, [], []
    if not ids:
        raise DomainError('cv_linkedin_link' if linkedin_link_only(prompt) else 'cv_file_required')
    previous = previous or {}
    same = (previous.get('options') or {}).get('cv_source') == source and previous.get('excerpts')
    if same and previous.get('source_ids') == ids:
        return ids, previous['excerpts'], list(previous.get('cv_unread') or [])
    assets, kinds = checked(account, ids, source)
    known = results_of(previous['excerpts'], previous.get('cv_unread')) if same else {}
    excerpts, unread = read(assets, kinds, known, account=account)
    return [str(asset.id) for asset in assets], excerpts, unread


# --- Reading -------------------------------------------------------------------------------

def kind_of(asset):
    """How a file is read: 'pdf', 'docx' or 'image'; None for a file no CV is made from."""
    return MIME.get(asset.mime_type) if asset.metadata.get('kind') in ('pdf', 'docx', 'image') else None


def entries(assets, kinds, account=None):
    """The files as their reads are taken: one {'account', 'asset_id', 'sha256', 'kind', 'pages'} each."""
    owner = str(getattr(account, 'pk', '') or '')
    return [{'account': owner, 'asset_id': str(asset.id), 'sha256': asset.sha256, 'kind': kind,
             'pages': int(asset.page_count or 0)}
            for asset, kind in zip(assets, kinds)]


def results_of(excerpts, unread=None):
    """What a draft's excerpts say each of its files gave, for the files read whole: {asset_id: result}."""
    partly = {str(entry.get('asset_id')) for entry in unread or [] if isinstance(entry, dict)}
    results = {}
    for excerpt in excerpts or []:
        identifier = str(excerpt.get('asset_id'))
        if identifier in partly:
            continue
        result = results.setdefault(identifier, {'pages': [], 'names': [], 'ocr_pages': 0, 'ocr_skipped': 0})
        result['pages'].append({'page': excerpt['page'], 'text': excerpt['text'],
                                **({'ocr': True} if excerpt.get('ocr') else {})})
        if excerpt.get('names') and not result['names']:
            result['names'] = list(excerpt['names'])
        result['ocr_pages'] += bool(excerpt.get('ocr'))
    return results


def _needs_ocr(result):
    return bool(result['ocr_pages'] or result['ocr_skipped'])


def shared(results):
    """Each file's result held to its share of the MAX_OCR_PAGES one draft takes, in the files' order.

    Each file is allowed what is left less a page for every file after it
    that needed OCR, and one page at least while any is left, so a long scan
    never leaves a screenshot after it unread. Every file was read with all
    of MAX_OCR_PAGES (reads.read_file); the pages read by OCR past its share
    are left out, and counted as not read (`ocr_skipped`), as are pages OCR
    never reached.
    """
    left, held = MAX_OCR_PAGES, []
    for index, result in enumerate(results):
        if result is None:
            held.append(None)
            continue
        later = sum(1 for other in results[index + 1:] if other is not None and _needs_ocr(other))
        allowed = max(min(1, left) if _needs_ocr(result) else 0, left - later)
        pages, used, dropped, first = [], 0, 0, False
        for page in result['pages']:
            if page.get('ocr') is True:
                if used >= allowed:
                    dropped += 1
                    first = first or page.get('page') == 1
                    continue
                used += 1
            pages.append(page)
        left = max(0, left - used)
        # Names read from a first page that is left out are not the file's to give.
        held.append({**result, 'pages': pages, 'names': [] if first else list(result['names']),
                     'ocr_pages': used, 'ocr_skipped': int(result['ocr_skipped']) + dropped})
    return held


def excerpts_of(files, results):
    """The excerpts of files read (as their reads kept them), and what of them was not read: (excerpts, unread).

    Every page with text, in the files' order, within the draft's OCR pages
    (shared): {'asset_id', 'page', 'text'} and, when it applies, 'ocr' and
    'names'. 'ocr' marks a page read from an image. 'names' are, on a file's
    first page with text, its largest lines at the top: on a CV and a
    LinkedIn export, the person's name (content.found_name). `unread`
    names each file not read whole: {'asset_id', 'pages'} with how many of
    its pages were left out, and 'whole' when none was read (a result of
    None: one the reader could not read). Files that give fewer than
    MIN_WORDS words between them are `cv_file_unreadable`.
    """
    excerpts, unread = [], []
    for entry, result in zip(files, shared(list(results))):
        if result is None:
            unread.append({'asset_id': entry['asset_id'], 'pages': max(1, entry['pages']), 'whole': True})
            continue
        if result['ocr_skipped']:
            unread.append({'asset_id': entry['asset_id'], 'pages': result['ocr_skipped']})
        names = list(result['names'])
        for page in result['pages']:
            text = str(page.get('text') or '')[:12000]
            if not text.strip():
                continue
            excerpt = {'asset_id': entry['asset_id'], 'page': page['page'], 'text': text}
            if page.get('ocr') is True:
                excerpt['ocr'] = True
            if names:
                excerpt['names'], names = names, []
            excerpts.append(excerpt)
    if sum(len(re.findall(r'[^\W\d_]{2,}', excerpt['text'])) for excerpt in excerpts) < MIN_WORDS:
        raise DomainError('cv_file_unreadable')
    return excerpts, unread


def read(assets, kinds, known=None, *, account):
    """Every page of text in `assets` as the reader kept it, in their order, and what was not read: (excerpts, unread).

    Nothing is read here, in a request or in the bot: each file is read once
    by `runreader` (cv/reads.py), and a file still waiting for it refuses the
    draft with `cv_reading` until it is read. A file the reader could not
    read is a file not read whole (excerpts_of). `known` is what the draft's
    files gave before, by file: a file in it needs no read, as the read may
    be gone with the file.
    """
    from . import reads
    known = known or {}
    files = entries(assets, kinds, account)
    rows = reads.ensure(account, [asset for asset in assets if str(asset.id) not in known])
    waiting = [row for row in rows.values() if row.status in reads.WAITING]
    if waiting:
        raise reads.refusal(waiting)
    return excerpts_of(files, [known[entry['asset_id']] if entry['asset_id'] in known
                               else reads.result_of(rows[entry['asset_id']]) for entry in files])


def for_model(excerpts):
    """A CV's excerpts as the model reads them: the page and its text, and whether OCR read it; the name hints stay here."""
    return [{key: value for key, value in excerpt.items() if key != 'names'} for excerpt in excerpts]
