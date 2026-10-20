"""Where a CV's facts come from: one message, the customer's LinkedIn profile, or their old CV.

The customer chooses first (`options.cv_source`). 'text' is the one message a
CV has always been made from. 'linkedin' is their LinkedIn profile, which our
server cannot open: LinkedIn needs a sign-in and forbids reading its pages by
program, so it is the profile saved with LinkedIn's own "Save to PDF", or
screenshots of it. 'file' is an old CV: a PDF, a Word file, photos or a scan.
In those two the file holds the facts and what the customer writes is notes
on top of it: the job they want now, what to change, what to add. A photo
sent there is a page to read, never the portrait.

The files are read once, when the draft is made (extraction.read_cv), and
what they say is kept with the draft as its excerpts. Nothing reads them
again: an update that keeps them keeps what was read, and a change to the CV
is made from the excerpts it was made from, after the files themselves are
gone (they are kept 24 hours).
"""
import re
import time

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
# Pages read by OCR for one draft, and how long all its files may take to read:
# the request that makes the draft has to answer well inside the proxy's 120 s.
MAX_OCR_PAGES = 10
READ_SECONDS = 75
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


def linkedin_link_only(text):
    """Whether a description is a LinkedIn profile's link and next to nothing else.

    It cannot be opened, so the customer is told how to save the profile as a
    PDF instead (`cv_linkedin_link`). A link inside a description with a CV's
    worth of facts is only a contact detail.
    """
    text = str(text or '')
    if not LINKEDIN_LINK.search(text):
        return False
    from .content import says_little
    return says_little(LINKEDIN_LINK.sub(' ', text))


def prepare(account, prompt, ids, options, previous=None):
    """The files of a new CV checked for its mode and read: (ids, excerpts).

    'text' takes none. 'linkedin' and 'file' take one to ten of the kinds
    their mode reads (KINDS); `previous` is the draft being updated, whose
    excerpts are kept when its files are. Refused: `cv_file_required` with no
    file, `cv_linkedin_link` when the description is only a LinkedIn link,
    `cv_file_kind` for a file the mode does not read, `cv_file_unreadable`
    for a protected PDF or files with no text in them.
    """
    source = mode(options)
    if not isinstance(ids, list):
        raise DomainError('invalid_parameters')
    if source == TEXT:
        if ids:
            raise DomainError('invalid_parameters')
        if linkedin_link_only(prompt):
            raise DomainError('cv_linkedin_link')
        return ids, []
    if not ids:
        raise DomainError('cv_linkedin_link' if linkedin_link_only(prompt) else 'cv_file_required')
    if len(ids) > max_files(account):
        raise DomainError('generation_limit')
    previous = previous or {}
    if (previous.get('source_ids') == ids and previous.get('excerpts')
            and (previous.get('options') or {}).get('cv_source') == source):
        return ids, previous['excerpts']
    from apps.core.policy import plan_limits
    from apps.core.services import owned_assets
    assets = owned_assets(account, ids)
    kinds = [MIME.get(asset.mime_type) if asset.metadata.get('kind') in ('pdf', 'docx', 'image') else None
             for asset in assets]
    if any(kind not in KINDS[source] for kind in kinds):
        raise DomainError('cv_file_kind')
    if any(asset.metadata.get('encrypted') for asset in assets):
        raise DomainError('cv_file_unreadable')
    if sum(asset.page_count for asset in assets) > min(MAX_PAGES, plan_limits(account)['max_ai_source_pages']):
        raise DomainError('generation_limit')
    return [str(asset.id) for asset in assets], read(assets, kinds)


def read(assets, kinds):
    """Every page of text in `assets`, in their order: {'asset_id', 'page', 'text'} and, when it applies, 'ocr' and 'names'.

    'ocr' marks a page read from an image. 'names' are, on a file's first
    page with text, its largest lines at the top: on a CV and a LinkedIn
    export, the person's name (content.require_name). A file that cannot be
    read gives no pages; files that give fewer than MIN_WORDS words between
    them are `cv_file_unreadable`.
    """
    from apps.core import storage
    from ..extraction import read_cv
    deadline = time.monotonic() + READ_SECONDS
    ocr_left = MAX_OCR_PAGES
    excerpts = []
    for asset, kind in zip(assets, kinds):
        seconds = deadline - time.monotonic()
        if seconds < 5:
            break
        try:
            result = read_cv(storage.local(asset.object_key), kind, ocr_pages=ocr_left, seconds=seconds)
        except DomainError:
            continue
        ocr_left = max(0, ocr_left - int(result.get('ocr_pages') or 0))
        names = [str(name)[:120] for name in result.get('names') or [] if isinstance(name, str)][:3]
        for page in result['pages']:
            if not isinstance(page, dict) or type(page.get('page')) is not int:
                continue
            text = str(page.get('text') or '')[:12000]
            if not text.strip():
                continue
            excerpt = {'asset_id': str(asset.id), 'page': page['page'], 'text': text}
            if page.get('ocr') is True:
                excerpt['ocr'] = True
            if names:
                excerpt['names'], names = names, []
            excerpts.append(excerpt)
    if sum(len(re.findall(r'[^\W\d_]{2,}', excerpt['text'])) for excerpt in excerpts) < MIN_WORDS:
        raise DomainError('cv_file_unreadable')
    return excerpts


def for_model(excerpts):
    """A CV's excerpts as the model reads them: the page and its text, and whether OCR read it; the name hints stay here."""
    return [{key: value for key, value in excerpt.items() if key != 'names'} for excerpt in excerpts]
